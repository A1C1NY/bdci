from copy import deepcopy
import json
from pathlib import Path

import pytest

from research_lab.autonomous import initialize, Research
from research_lab.autonomy_worker import FixtureWorker
from research_lab.storage import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def setup(tmp_path, **changes):
    config = read_json(ROOT / "config/projects/autonomous-fixture.json")
    config["development"] = str(ROOT / "config/projects/threshold-dev.json")
    config["evaluation"] = str(ROOT / "config/projects/threshold-holdout.json")
    config["sources"][0]["path"] = str(ROOT / "config/projects/fixture-literature.txt")
    config.update(changes)
    path = tmp_path / "config.json"
    write_json(path, config)
    root = tmp_path / "autonomous"
    initialize(path, root)
    return root


class Spy(FixtureWorker):
    def __init__(self):
        self.calls = []

    def generate(self, alias, stage, payload, schema, limit):
        self.calls.append(deepcopy(payload))
        return super().generate(alias, stage, payload, schema, limit)


def test_full_flow_without_human_approval_and_idempotent_resume(tmp_path):
    root = setup(tmp_path)
    worker = Spy()
    state = Research(root, worker).run()
    assert state["status"] == "completed"
    assert state["model_calls"] == 0 and state["worker_calls"] == 11
    assert state["evaluation_exposed"]
    assert all(r["actor_type"] == "model_review_panel" for r in state["reviews"])
    assert state["analysis"]["gain"] == .5
    assert '"test1"' not in json.dumps(worker.calls)  # Evaluation labels/rows never enter worker prompts.
    count = len(worker.calls)
    assert Research(root, worker).run()["status"] == "completed"
    assert len(worker.calls) == count
    report = root / "evidence/deliverables"
    assert (report / "paper.tex").exists()
    assert read_json(report / "claims.json")["reader_accuracy_established"] is False
    assert state["deliverables"]["ready_for_external_submission"] is False


def test_model_revision_is_executed_not_auto_accepted(tmp_path):
    class Critic(Spy):
        def generate(self, alias, stage, payload, schema, limit):
            value, cost = super().generate(alias, stage, payload, schema, limit)
            if "design-0-critic" in stage:
                value.update(verdict="revise", issues=["Revise the bounded candidate before evaluating."], reason="The first design requires a bounded correction.")
            return value, cost
    root = setup(tmp_path)
    state = Research(root, Critic()).run()
    assert state["status"] == "completed"
    assert [x["status"] for x in state["trials"]] == ["rejected", "evaluated"]
    assert "candidate-0" not in state["operations"]
    assert state["frozen"]["selected"] == {"threshold": .55}


def test_paper_revision_never_repeats_evaluation(tmp_path):
    class Critic(Spy):
        def generate(self, alias, stage, payload, schema, limit):
            result, cost = super().generate(alias, stage, payload, schema, limit)
            if "paper-0-critic" in stage:
                result.update(verdict="revise", issues=["Clarify that this is synthetic validation only."], reason="Draft needs a clearer scope statement.")
            return result, cost
    state = Research(setup(tmp_path), Critic()).run()
    assert state["status"] == "completed" and state["draft_revision"] == 1
    assert len([k for k in state["operations"] if k.endswith("-evaluation")]) == 2


def test_negative_result_is_retained_and_exported(tmp_path):
    class Negative(Spy):
        def generate(self, alias, stage, payload, schema, limit):
            result, cost = super().generate(alias, stage, payload, schema, limit)
            if payload["role"] == "propose":
                result["method"] = {"threshold": .95}
            return result, cost
    root = setup(tmp_path)
    state = Research(root, Negative()).run()
    assert state["status"] == "completed"
    assert state["best_method"] == {"threshold": .9}
    assert state["analysis"]["gain"] == 0
    assert read_json(root / "evidence/deliverables/claims.json")["gain_criterion_met"] is False


def test_fabricated_sources_exhaust_search_without_evaluation(tmp_path):
    class Fabricator(Spy):
        def generate(self, alias, stage, payload, schema, limit):
            result, cost = super().generate(alias, stage, payload, schema, limit)
            if payload["role"] == "propose":
                result["sources"][0]["excerpt"] = "A fabricated quotation that was never in the source."
            return result, cost
    state = Research(setup(tmp_path), Fabricator()).run()
    assert state["status"] == "stopped" and not state["evaluation_exposed"]
    assert all(t["status"] == "rejected" for t in state["trials"])


def test_budget_is_admitted_before_worker_call(tmp_path):
    class Costly(Spy):
        def reservation(self, alias):
            return 100
    worker = Costly()
    state = Research(setup(tmp_path), worker).run()
    assert state["status"] == "budget_exhausted" and not worker.calls


def test_gateway_wait_has_no_unknown_charge_and_can_resume(tmp_path):
    class Offline(Spy):
        def ready(self, alias):
            raise TimeoutError("Unreachable fixture network")
    root = setup(tmp_path)
    state = Research(root, Offline()).run()
    assert state["status"] == "waiting_for_gateway" and state["worker_calls"] == 0
    assert Research(root, Spy()).run()["status"] == "completed"


def test_unknown_request_retains_reservation_and_is_not_retried(tmp_path):
    class Interrupted(Spy):
        def reservation(self, alias):
            return 50

        def generate(self, *args):
            raise KeyboardInterrupt("simulated crash after intent")
    root = setup(tmp_path, model_budget={"deepseek": 1000, "kimi": 1000})
    with pytest.raises(KeyboardInterrupt):
        Research(root, Interrupted()).run()
    state = read_json(root / "autonomy-state.json")
    assert state["charged_or_reserved"]["kimi"] == 50
    worker = Spy()
    state = Research(root, worker).run()
    assert state["status"] == "needs_attention" and not worker.calls
    assert state["charged_or_reserved"]["kimi"] == 50


def test_committed_receipt_recovers_interrupted_state_save(tmp_path, monkeypatch):
    root = setup(tmp_path)
    state = Research(root, Spy()).run(max_steps=1)
    state["operations"]["baseline-development"]["status"] = "running"
    state["phase"] = "baseline"
    write_json(root / "autonomy-state.json", state)
    monkeypatch.setattr("research_lab.autonomous.evaluate", lambda *args: pytest.fail("duplicate experiment"))
    assert Research(root, Spy()).run(max_steps=1)["phase"] == "propose"


def test_mutation_blocks_resume_and_other_projects_are_isolated(tmp_path):
    first = setup(tmp_path / "first")
    second = setup(tmp_path / "second")
    Research(first, Spy()).run()
    Research(second, Spy()).run()
    (first / "evidence/analysis/result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        Research(first, Spy()).run()
    assert Research(second, Spy()).run()["status"] == "completed"


def test_cannot_search_again_after_evaluation(tmp_path):
    root = setup(tmp_path)
    state = Research(root, Spy()).run(max_steps=1)
    state.update(evaluation_exposed=True, phase="propose", status="ready")
    write_json(root / "autonomy-state.json", state)
    assert Research(root, Spy()).run()["status"] == "needs_attention"


def test_development_evaluation_overlap_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        setup(tmp_path, evaluation=str(ROOT / "config/projects/threshold-dev.json"))


def test_binding_mismatch_and_fixture_route_cannot_pass(tmp_path):
    class BadBinding(Spy):
        def generate(self, alias, stage, payload, schema, limit):
            result, cost = super().generate(alias, stage, payload, schema, limit)
            if payload["role"] == "review":
                result["binding"] = "0" * 64
            return result, cost
    root = setup(tmp_path)
    assert Research(root, BadBinding()).run()["status"] == "needs_attention"
    real = Spy()
    real.fixture = False
    with pytest.raises(ValueError, match="Fixture workers"):
        Research(root, real).run()


def test_excess_reported_usage_is_preserved(tmp_path):
    class Overrun(Spy):
        def reservation(self, alias):
            return 10

        def generate(self, *args):
            result, _ = super().generate(*args)
            return result, 12
    state = Research(setup(tmp_path, model_budget={"deepseek": 100, "kimi": 100}), Overrun()).run()
    assert state["status"] == "budget_exhausted"
    assert state["charged_or_reserved"]["kimi"] == 12


def test_deadline_and_trial_timeout_cannot_be_waiting_for_gateway(tmp_path, monkeypatch):
    root = setup(tmp_path)
    def timeout(*args):
        raise TimeoutError("Local experiment time limit exceeded")
    monkeypatch.setattr("research_lab.autonomous.evaluate", timeout)
    assert Research(root, Spy()).run()["status"] == "deadline_exceeded"


def test_stale_evaluator_retains_context_and_never_exposes_labels_to_policy(tmp_path):
    from research_lab.autonomy_domains import evaluate
    import time
    record = {"uid": "one", "type": "T1", "M_new": "I moved to Austin.", "M_old": "I live in Seattle.",
              "timestamps": [], "probing_queries": {"dim1": "Where do I live?"},
              "haystack_session": [[{"role": "user", "content": "I live in Seattle."}],
                                   [{"role": "user", "content": "I moved to Austin."}]]}
    write_json(tmp_path / "inputs/development.json", [record])
    config = {"domain": "stale_retrieval", "context_bytes": 1000, "max_local_seconds": 60}
    result = evaluate(tmp_path, config, {"relevance": 1, "recency": 0, "change": 0}, "development", tmp_path / "result", time.time() + 60)
    assert result["score"] == 1 and result["fixture_only"] is False
    assert "M_new" not in read_json(tmp_path / "result/contexts.json")[0]


def test_dashboard_projection_is_read_only_and_hides_worker_routes(tmp_path):
    from research_lab.dashboard_data import DashboardStore
    root = setup(tmp_path / "projects")
    Research(root, Spy()).run()
    class Ledger:
        def snapshot(self):
            return {"models": {}, "recent_requests": []}
    state = read_json(root / "autonomy-state.json")
    state["worker_identity"]["secret_gateway_address"] = "never-expose-this-route"
    write_json(root / "autonomy-state.json", state)
    before = (root / "autonomy-state.json").read_bytes()
    store = DashboardStore(tmp_path, Ledger())
    snapshot = store.snapshot(force=True)
    assert snapshot["projects"][0]["autonomous"] is True
    assert snapshot["projects"][0]["model_calls"] == 0
    assert "never-expose-this-route" not in json.dumps(snapshot)
    assert before == (root / "autonomy-state.json").read_bytes()
    with pytest.raises(ValueError, match="allowlist"):
        store.artifact("projects/autonomous/evidence/proposal-0/request.json")


def test_stale_domain_completes_with_scripted_worker_contract(tmp_path):
    class StaleWorker(Spy):
        fixture = False
        identity = {"backend": "scripted-test-only", "routes": {
            "deepseek": {"model": "test-a", "base_url": "http://example.invalid"},
            "kimi": {"model": "test-b", "base_url": "http://example.invalid"}}}

        def generate(self, *args):
            result, cost = super().generate(*args)
            if args[2]["role"] == "propose":
                result["method"] = {"relevance": .7, "recency": .2, "change": .1}
            return result, cost
    paths = []
    for uid, city in (("dev", "Austin"), ("eval", "Paris")):
        path = tmp_path / (uid + ".json")
        write_json(path, [{"uid": uid, "type": "T1", "M_old": "I live in Seattle.", "M_new": "I moved to " + city + ".",
                           "timestamps": [], "probing_queries": {"dim1": "Where should I live?"},
                           "haystack_session": [[{"role": "user", "content": "I live in Seattle."}],
                                                [{"role": "user", "content": "I moved to " + city + "."}]]}])
        paths.append(str(path))
    root = setup(tmp_path, domain="stale_retrieval", development=paths[0], evaluation=paths[1],
                 baseline={"relevance": 1, "recency": 0, "change": 0}, data_exposure="reused",
                 model_budget={"deepseek": 1000, "kimi": 1000})
    worker = StaleWorker()
    state = Research(root, worker).run()
    assert state["status"] == "completed"
    assert state["analysis"]["metric"] == "literal_update_inclusion"
    assert state["deliverables"]["research_outcome"] == "inconclusive_or_negative"
    assert '"M_new"' not in json.dumps(worker.calls)
    with pytest.raises(ValueError, match="Fixture workers"):
        Research(root, FixtureWorker()).run()


def test_native_bridge_uses_swarm_and_durable_stage_accounting(tmp_path, monkeypatch):
    from research_lab.autonomy_worker import NativeWorker
    import research_lab.framework as framework
    import research_lab.native_research as native
    monkeypatch.setattr(framework, "ROOT", tmp_path)
    called = []
    def run(stage, tasks, **kwargs):
        called.append((stage, tasks, kwargs))
        write_json(tmp_path / "outputs" / ("v4-" + stage) / "requests/test.json", {"charged_tokens": 17})
        return {"result": {"answer": "Synthetic native bridge contract"}}
    monkeypatch.setattr(native, "run_tasks", run)
    worker = NativeWorker.__new__(NativeWorker)
    value, charged = worker.generate("kimi", "bounded-test", {"role": "review"}, {"type": "object"}, 100)
    assert charged == 17 and "answer" in value
    assert called[0][2] == {"stage_limit": 100, "parallel": False}
    assert called[0][1][0]["model"] == "kimi"


def test_oversized_worker_context_does_not_reserve_or_call(tmp_path):
    class TinyContext(Spy):
        def input_limit(self, alias):
            return 10
    worker = TinyContext()
    state = Research(setup(tmp_path), worker).run()
    assert state["status"] == "needs_attention" and not worker.calls
    assert state["worker_calls"] == 0
    assert sum(state["charged_or_reserved"].values()) == 0
