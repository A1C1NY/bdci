from copy import deepcopy
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

import pytest

from research_lab.agents import LocalPlanner
from research_lab.campaign import run_campaign, verify_campaign
from research_lab.campaign_plan import load_campaign
from research_lab.campaign_report import audit_campaign_content
from research_lab.framework import BudgetExceeded, reserve_research_attempt, verify_artifact_manifest
from research_lab.handoff import export_review, import_feedback
from research_lab.storage import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path):
    value = read_json(ROOT / "experiments/memory_search/campaign.json")
    value["development_seeds"] = [11, 23]
    value["holdout_seeds"] = [101, 211]
    value["candidates"] = ["events_only", "keyed_memory"]
    value["search"] = {"max_trials": 2, "patience": 2, "min_improvement": 0.005}
    # Genuine subprocess fixture: development winner reverses on unseen seeds.
    (tmp_path / "experiment.py").write_text('''import argparse, hashlib, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--method'); p.add_argument('--seed', type=int); p.add_argument('--output')
a = p.parse_args()
scores = {'recent_window': 0.5, 'events_only': 0.7, 'keyed_memory': 0.9, 'first_write': 0.4}
score = scores[a.method] if a.seed < 100 else 1 - scores[a.method]
Path(a.output).write_text(json.dumps({'method': a.method, 'seed': a.seed,
 'metrics': {'accuracy': score}, 'provenance': {'dataset_sha256': hashlib.sha256(str(a.seed).encode()).hexdigest()}}))
''', encoding="utf-8")
    shutil.copyfile(ROOT / "experiments/memory_search/protocol.md", tmp_path / "protocol.md")
    path = tmp_path / "campaign.json"
    write_json(path, value)
    return path


@pytest.fixture
def completed(config, tmp_path):
    root = tmp_path / "campaign"
    run_campaign(config, root)
    return root


def test_negative_holdout_never_reselects(completed):
    state = read_json(completed / "state.json")
    assert state["status"] == "completed"
    assert state["incumbent"] == "keyed_memory"
    assert len(state["history"]) == 2
    assert verify_campaign(completed) == []
    claims = read_json(completed / "claims.json")["claims"]
    selected = next(item for item in claims if item["method"] == "keyed_memory")
    assert selected["paired_delta_mean"] == pytest.approx(-0.4)
    assert "worse than" in (completed / "paper_draft.md").read_text(encoding="utf-8")
    assert len(state["budget"]["reservations"]) == 14
    assert read_json(completed / "resource_report.json")["attempt_records"] == 14


def test_pause_resume_preserves_results_and_no_early_holdout(config, tmp_path):
    root = tmp_path / "run"
    state = run_campaign(config, root, max_trials=1)
    assert state["status"] == "paused"
    assert not (root / "runs/holdout").exists()
    assert not (root / "selection.json").exists()
    result = next((root / "runs/trial_001/jobs").glob("*/attempt_1/result.json"))
    before = result.stat().st_mtime_ns
    done = run_campaign(config, root, resume=True)
    assert done["status"] == "completed" and result.stat().st_mtime_ns == before
    assert verify_campaign(root) == []
    assert run_campaign(config, root, resume=True) == done


def test_budget_exhaustion_launches_nothing(config, tmp_path):
    value = read_json(config)
    value["budget"]["max_attempts"] = 1
    write_json(config, value)
    with pytest.raises(BudgetExceeded):
        run_campaign(config, tmp_path / "limited")
    state = read_json(tmp_path / "limited/state.json")
    assert state["status"] == "budget_exhausted" and not state["budget"]["reservations"]
    assert not (tmp_path / "limited/runs").exists()


def test_retry_and_resume_budget_are_not_reset(config, tmp_path):
    script = tmp_path / "experiment.py"
    script.write_text("from pathlib import Path\nimport sys\n"
                      "if Path.cwd().name == 'attempt_1':\n    sys.exit(7)\n" + script.read_text(), encoding="utf-8")
    root = tmp_path / "run"
    state = run_campaign(config, root, max_trials=1)
    assert len(state["budget"]["reservations"]) == 8
    state = run_campaign(config, root, resume=True)
    assert len(state["budget"]["reservations"]) == 28
    resources = read_json(root / "resource_report.json")
    assert resources["failed_or_interrupted_attempts"] == 14
    assert verify_campaign(root) == []


def test_audit_recomputes_claims_and_draft(completed):
    claims = read_json(completed / "claims.json")
    claims["claims"][1]["mean"] = 999
    write_json(completed / "claims.json", claims)
    assert "Numerical claims differ from raw evidence" in audit_campaign_content(completed)["errors"]
    assert verify_campaign(completed)


def test_completed_result_tampering_is_not_silently_rerun(completed, config):
    result = next((completed / "runs/holdout/jobs").glob("*/attempt_1/result.json"))
    result.write_text("{}")
    with pytest.raises(ValueError, match="Completed campaign changed"):
        run_campaign(config, completed, resume=True)


def test_source_change_rejects_resume(config, tmp_path):
    root = tmp_path / "run"
    run_campaign(config, root, max_trials=1)
    (tmp_path / "protocol.md").write_text("changed source")
    with pytest.raises(ValueError, match="changed"):
        run_campaign(config, root, resume=True)


@pytest.mark.parametrize("mutation", [
    {"holdout_seeds": [11, 211]}, {"candidates": ["../bad"]},
    {"budget": {"max_attempts": True, "max_timeout_seconds": 100}},
    {"search": {"max_trials": 2, "patience": 2, "min_improvement": float("nan")}},
])
def test_invalid_protocol_rejected(config, mutation):
    value = read_json(config)
    value.update(mutation)
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_campaign(config)


def test_budget_reservations_are_pure_and_bounded():
    ledger = {"max_attempts": 2, "max_timeout_seconds": 15, "reservations": []}
    first = reserve_research_attempt(ledger, "one", 10)
    assert ledger["reservations"] == []
    with pytest.raises(BudgetExceeded):
        reserve_research_attempt(first, "two", 10)
    second = reserve_research_attempt(first, "two", 5)
    with pytest.raises(BudgetExceeded):
        reserve_research_attempt(second, "three", 0.1)
    corrupted = deepcopy(second)
    corrupted["reservations"][0]["timeout_seconds"] = -1
    with pytest.raises(ValueError):
        reserve_research_attempt(corrupted, "four", 1)


def test_patience_stops_unproductive_candidates():
    assert LocalPlanner().propose(["a", "b", "c"], [
        {"candidate": "a", "accepted": False}, {"candidate": "b", "accepted": False}], max_trials=3, patience=2) is None


def test_review_kit_reproduces_in_fresh_process(completed, tmp_path):
    output = tmp_path / "kit.zip"
    export_review(completed, output)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(output) as archive:
        assert not any(".env" in name or "/.git/" in name for name in archive.namelist())
        archive.extractall(extracted)
    assert verify_artifact_manifest(extracted, read_json(extracted / "EXPORT_MANIFEST.json")) == []
    for arguments in (["verify-campaign", "campaign"],
                      ["campaign", "--config", "reproduce.json", "--output", "reproduced"],
                      ["verify-campaign", "reproduced"]):
        result = subprocess.run([sys.executable, "-I", "scripts/research.py", *arguments], cwd=extracted,
                                text=True, capture_output=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
    assert read_json(extracted / "reproduced/summary.json") == read_json(completed / "summary.json")
    with pytest.raises(FileExistsError):
        export_review(completed, output)


def test_feedback_import_preserves_original(completed, tmp_path):
    before = (completed / "campaign_manifest.json").read_bytes()
    feedback = tmp_path / "feedback.json"
    write_json(feedback, {"reviewer": "test-human", "comments": [
        {"id": "r1", "severity": "major", "comment": "Evaluate unseen tasks", "action": "Register a new experiment"}]})
    result = import_feedback(completed, feedback, tmp_path / "revision")
    assert result["experiments_changed"] is False
    assert (completed / "campaign_manifest.json").read_bytes() == before
    assert verify_campaign(completed) == []
