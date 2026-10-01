from copy import deepcopy
import json

import pytest

from research_lab.project import Adapter, Project, validate
from research_lab.project_adapters import adapters
from research_lab.storage import read_json, write_json


def spec():
    return {"schema_version": 5, "id": "test", "question": "Local orchestration test",
            "model_token_limit": 100, "stages": [
                {"id": "source", "adapter": "artifact", "review": False, "config": {"x": 1}},
                {"id": "gate", "adapter": "artifact", "needs": ["source"], "role": "freeze"},
                {"id": "end", "adapter": "artifact", "needs": ["gate"], "review": False}]}


def create(tmp_path, config=None, registry=None):
    path = tmp_path / "config.json"
    write_json(path, config or spec())
    project = Project(tmp_path / "projects" / "demo", registry)
    project.initialize(path)
    return project, path


def accept(project, sid):
    packet = project.review_packet(sid)
    return project.decide(sid, "accept", "test supervisor", "checked local fixture", packet["binding"])


def test_restart_reuses_completed_and_waits_for_bound_review(tmp_path):
    project, _ = create(tmp_path)
    state = project.advance()
    assert [s["status"] for s in state["stages"]] == ["accepted", "awaiting_review", "pending"]
    restarted = Project(project.root)
    assert restarted.advance() == project.status()
    accept(restarted, "gate")
    assert restarted.advance()["status"] == "completed"
    assert all(s["attempts"] == 1 for s in restarted.advance()["stages"])


def test_old_review_does_not_accept_revised_output_and_history_survives(tmp_path):
    project, path = create(tmp_path)
    project.advance()
    old = project.review_packet("gate")
    config = spec()
    config["stages"][0]["config"]["x"] = 2
    write_json(path, config)
    project.revise(path, "owner", "new evidence")
    project.advance()
    with pytest.raises(ValueError, match="binding changed"):
        project.decide("gate", "accept", "owner", "stale acceptance", old["binding"])
    state = read_json(project.path)
    assert len(state["stages"]["source"]["attempts"]) == 2
    assert len(state["config_history"]) == 2
    accept(project, "gate")


def test_modified_artifact_invalidates_descendants_without_status_writes(tmp_path):
    project, _ = create(tmp_path)
    project.advance()
    accept(project, "gate")
    project.advance()
    before = project.path.read_bytes()
    record = read_json(project.path)["stages"]["source"]["attempts"][-1]
    write_json(project.root / record["result_path"], {"tampered": True})
    assert [s["status"] for s in project.status()["stages"]] == ["stale"] * 3
    assert project.path.read_bytes() == before


def fail(context):
    raise RuntimeError("injected transport failure")


def paid(context):
    return {"accounting": {"charged_or_reserved": 12}}


def test_failed_attempt_not_silently_retried_and_budget_retained(tmp_path):
    config = spec()
    config["stages"] = [{"id": "work", "adapter": "paid", "token_limit": 60}]
    registry = {"paid": Adapter(fail, paid=True)}
    project, _ = create(tmp_path, config, registry)
    assert project.advance()["stages"][0]["attempts"] == 0
    with pytest.raises(RuntimeError):
        project.advance(allow_models=True)
    assert project.advance(allow_models=True)["stages"][0]["attempts"] == 1
    assert project.status()["model_tokens_charged_or_reserved"] == 60
    project.retry("work", "owner", "explicit new attempt")
    with pytest.raises(ValueError, match="budget exhausted"):
        project.advance(allow_models=True)


def test_success_settles_project_reservation(tmp_path):
    config = spec()
    config["stages"] = [{"id": "work", "adapter": "paid", "token_limit": 60}]
    project, _ = create(tmp_path, config, {"paid": Adapter(paid, paid=True)})
    assert project.advance(allow_models=True)["model_tokens_charged_or_reserved"] == 12


@pytest.mark.parametrize("action,status", [("reject", "rejected"), ("request_changes", "changes_requested"), ("terminate", "rejected")])
def test_decision_controls_downstream(tmp_path, action, status):
    project, _ = create(tmp_path)
    project.advance()
    packet = project.review_packet("gate")
    project.decide("gate", action, "owner", "test reason", packet["binding"])
    assert project.status()["stages"][1]["status"] == status
    if action == "terminate":
        with pytest.raises(ValueError, match="terminated"):
            project.advance()
    else:
        assert project.advance()["stages"][2]["attempts"] == 0


def test_holdout_requires_freeze_and_cannot_be_retried_or_revised(tmp_path):
    config = spec()
    config["stages"][-1]["split"] = "holdout"
    project, path = create(tmp_path, config)
    project.advance()
    assert not project.status()["holdout_exposed"]
    accept(project, "gate")
    project.advance()
    assert project.status()["holdout_exposed"]
    with pytest.raises(ValueError, match="immutable"):
        project.revise(path, "owner", "tune after seeing results")
    config["stages"][-1]["needs"] = ["source"]
    with pytest.raises(ValueError, match="freeze"):
        validate(config, adapters())


def test_downstream_protocol_revision_requires_new_freeze(tmp_path):
    project, path = create(tmp_path)
    project.advance()
    accept(project, "gate")
    config = spec()
    config["stages"][-1]["config"] = {"new_metric": True}
    write_json(path, config)
    project.revise(path, "owner", "new evaluation")
    assert project.status()["stages"][1]["status"] == "pending"
    project.advance()
    assert project.status()["stages"][2]["attempts"] == 0


def test_proposal_cannot_depend_transitively_on_holdout(tmp_path):
    config = spec()
    config["stages"][-1]["split"] = "holdout"
    config["stages"].extend([
        {"id": "analysis", "adapter": "artifact", "needs": ["end"]},
        {"id": "proposal", "adapter": "artifact", "needs": ["analysis"], "role": "proposal"}])
    with pytest.raises(ValueError, match="cannot depend"):
        validate(config, adapters())


@pytest.mark.parametrize("mutation", ["cycle", "adapter", "automatic_freeze", "negative_budget", "duplicate"])
def test_invalid_protocols_rejected(mutation):
    config = spec()
    if mutation == "cycle":
        config["stages"][0]["needs"] = ["end"]
    elif mutation == "adapter":
        config["stages"][0]["adapter"] = "os.system"
    elif mutation == "automatic_freeze":
        config["stages"][1]["review"] = False
    elif mutation == "negative_budget":
        config["model_token_limit"] = -1
    else:
        config["stages"].append(deepcopy(config["stages"][0]))
    with pytest.raises(ValueError):
        validate(config, adapters())


def test_input_snapshot_is_independent_and_detects_tampering(tmp_path):
    write_json(tmp_path / "input.json", {"value": 1})
    config = spec()
    config["stages"][0]["inputs"] = {"source": "input.json"}
    project, _ = create(tmp_path, config)
    write_json(tmp_path / "input.json", {"value": 2})
    project.advance()
    state = read_json(project.path)
    result = read_json(project.root / state["stages"]["source"]["attempts"][-1]["result_path"])
    assert result["values"]["source"]["value"] == 1
    write_json(project.root / state["inputs"]["source"]["source"]["path"], {"tampered": 1})
    assert project.status()["stages"][0]["status"] == "stale"


def test_output_schema_failure_not_eligible_for_review(tmp_path):
    config = spec()
    config["stages"][0]["output_schema"] = {"type": "object", "required": ["nonexistent"]}
    project, _ = create(tmp_path, config)
    with pytest.raises(Exception, match="required property"):
        project.advance()
    assert project.status()["stages"][0]["status"] == "failed"
    with pytest.raises(ValueError):
        project.review_packet("source")


def test_crash_intent_requires_explicit_retry(tmp_path):
    project, _ = create(tmp_path)
    state = read_json(project.path)
    state["stages"]["source"] = {"status": "running", "attempts": [{"id": 1, "started_at": "fixture"}]}
    write_json(project.path, state)
    assert project.advance()["stages"][0]["attempts"] == 1
    project.retry("source", "owner", "checked interrupted process")
    assert project.advance()["stages"][0]["attempts"] == 2


def test_dashboard_and_cli_use_the_project_state(tmp_path, capsys):
    from research_lab.cli import main
    from research_lab.dashboard_data import DashboardStore
    project, _ = create(tmp_path)
    project.advance()
    assert main(["project", "status", str(project.root)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "awaiting_supervisor"
    class Ledger:
        def snapshot(self):
            return {"models": {}, "recent_requests": []}
    snapshot = DashboardStore(tmp_path, Ledger()).snapshot(force=True)
    assert snapshot["projects"][0]["stages"] == project.status()["stages"]
    assert snapshot["totals"]["pending_reviews"] == 1
    assert any(e["owner"] == "test" for e in snapshot["events"])
