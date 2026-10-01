from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

from research_lab.executor import execute, validate_result
from research_lab.pipeline import run, verify_run
from research_lab.plan import load_plan
from research_lab.report import summarize
from research_lab.storage import read_json, run_lock, write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plan_path(tmp_path):
    source = ROOT / "experiments" / "memory_demo"
    shutil.copyfile(source / "experiment.py", tmp_path / "experiment.py")
    value = read_json(source / "plan.json")
    value["seeds"] = [11, 23]
    path = tmp_path / "plan.json"
    write_json(path, value)
    return path


def test_end_to_end_same_inputs_and_measured_outputs(plan_path, tmp_path):
    root = tmp_path / "run"
    state = run(plan_path, root)
    assert state["status"] == "completed"
    assert verify_run(root) == []
    results = {k: read_json(root / v["result_path"]) for k, v in state["jobs"].items()}
    for seed in [11, 23]:
        a = results[f"recent_window__{seed}"]
        b = results[f"keyed_memory__{seed}"]
        assert a["provenance"]["dataset_sha256"] == b["provenance"]["dataset_sha256"]
        for result in (a, b):
            actual_correct = sum(r["expected"] == r["predicted"] for r in result["predictions"])
            assert result["metrics"]["accuracy"] == actual_correct / 80
    draft = (root / "paper_draft.md").read_text(encoding="utf-8")
    assert "not by a language model" in draft
    assert "No literature sources were supplied" in draft
    assert read_json(root / "resource_report.json")["total_attempts"] == 4


def test_resume_reuses_verified_jobs(plan_path, tmp_path):
    root = tmp_path / "run"
    first = run(plan_path, root, max_jobs=1)
    assert first["status"] == "paused"
    assert not (root / "paper_draft.md").exists()
    job = first["jobs"]["recent_window__11"]
    result = root / job["result_path"]
    before = result.stat().st_mtime_ns
    done = run(plan_path, root, resume=True)
    assert done["status"] == "completed"
    assert result.stat().st_mtime_ns == before
    assert len(done["jobs"]["recent_window__11"]["attempts"]) == 1
    assert verify_run(root) == []


def test_tampered_result_is_detected_then_rerun(plan_path, tmp_path):
    root = tmp_path / "run"
    first = run(plan_path, root)
    job = first["jobs"]["recent_window__11"]
    (root / job["result_path"]).write_text("{}", encoding="utf-8")
    assert verify_run(root)
    done = run(plan_path, root, resume=True)
    assert len(done["jobs"]["recent_window__11"]["attempts"]) == 2
    assert verify_run(root) == []


def test_changed_plan_refuses_resume(plan_path, tmp_path):
    root = tmp_path / "run"
    run(plan_path, root, max_jobs=1)
    plan = read_json(plan_path)
    plan["hypothesis"] += " changed"
    write_json(plan_path, plan)
    with pytest.raises(ValueError, match="changed"):
        run(plan_path, root, resume=True)


def test_archived_input_tampering_refuses_resume(plan_path, tmp_path):
    root = tmp_path / "run"
    run(plan_path, root, max_jobs=1)
    (root / "inputs" / "experiment.py").write_text("print('modified')", encoding="utf-8")
    with pytest.raises(ValueError, match="Archived inputs changed"):
        run(plan_path, root, resume=True)


def test_failed_attempt_retries_and_counts_cost(plan_path, tmp_path):
    script = tmp_path / "experiment.py"
    original = script.read_text(encoding="utf-8")
    script.write_text("from pathlib import Path\nimport sys\n"
                      "if Path.cwd().name == 'attempt_1':\n    sys.exit(7)\n" + original,
                      encoding="utf-8")
    root = tmp_path / "run"
    state = run(plan_path, root)
    assert all(len(job["attempts"]) == 2 for job in state["jobs"].values())
    resources = read_json(root / "resource_report.json")
    assert resources["total_attempts"] == 8
    assert resources["failed_attempts"] == 4


def test_exhausted_jobs_never_produce_paper(plan_path, tmp_path):
    (tmp_path / "experiment.py").write_text("raise RuntimeError('expected failure')", encoding="utf-8")
    root = tmp_path / "run"
    with pytest.raises(RuntimeError, match="attempts exhausted"):
        run(plan_path, root)
    assert read_json(root / "state.json")["status"] == "failed"
    assert not (root / "paper_draft.md").exists()
    assert verify_run(root)


def test_timeout_is_failure(tmp_path):
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    result = execute(script, "method", 0, tmp_path / "attempt", 0.2, "accuracy")
    assert result["status"] == "failed"
    assert "exceeded" in result["error"]
    assert result["wall_seconds"] < 10


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.8"])
def test_invalid_metrics_rejected(tmp_path, value):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"method": "method", "seed": 1,
                               "metrics": {"accuracy": value}, "provenance": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Non-finite"):
        validate_result(path, "method", 1, "accuracy")


def test_result_identity_is_checked(tmp_path):
    path = tmp_path / "result.json"
    write_json(path, {"method": "wrong", "seed": 1, "metrics": {"accuracy": 0.5}, "provenance": {}})
    with pytest.raises(ValueError, match="identity"):
        validate_result(path, "method", 1, "accuracy")


def test_negative_findings_are_not_relabelled_as_positive(plan_path):
    plan, _ = load_plan(plan_path)
    rows = [{"method": method, "seed": seed, "result": {"metrics": {"accuracy": score}}}
            for method, score in [("recent_window", 0.8), ("keyed_memory", 0.3)] for seed in [11, 23]]
    result = summarize(plan, rows)
    assert result["methods"][1]["paired_delta_mean"] == pytest.approx(-0.5)


def test_mismatched_evaluation_data_refuses_comparison(plan_path):
    plan, _ = load_plan(plan_path)
    rows = [{"method": method, "seed": seed,
             "result": {"metrics": {"accuracy": 0.5}, "provenance": {"dataset_sha256": method}}}
            for method in plan["methods"] for seed in plan["seeds"]]
    with pytest.raises(ValueError, match="different evaluation data"):
        summarize(plan, rows)


def test_exclusive_lock_prevents_second_writer(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another process"):
            with run_lock(tmp_path):
                pass


@pytest.mark.parametrize("mutation", [{"seeds": [1, 1]}, {"methods": ["../bad", "ok"]},
                                     {"timeout_seconds": float("inf")}, {"max_attempts": 0}])
def test_bad_plan_rejected(plan_path, mutation):
    value = read_json(plan_path)
    value.update(mutation)
    plan_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(plan_path)


def test_cli_can_run_from_another_directory(plan_path, tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"),
                             "validate-plan", str(plan_path)], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True
