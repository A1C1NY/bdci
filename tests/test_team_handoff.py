import copy
import importlib.util
from pathlib import Path
import shutil

import pytest

from research_lab.project import Adapter, Project
from research_lab.project_adapters import adapters
from research_lab.storage import read_json, write_json
from research_lab.study import initialize, ROOT
from research_lab import stale_adapters_v5 as study_adapters
from research_lab.model_config import load_models, get_key


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_member_setup_no_reset_and_env_override(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "config/models.example.json", tmp_path / "config/models.example.json")
    shutil.copyfile(ROOT / ".env.example", tmp_path / ".env.example")
    script = load_script("setup_member")
    script.setup("alice", 500000, 700000, root=tmp_path)
    monkeypatch.setenv("RESEARCH_LAB_MODELS_CONFIG", str(tmp_path / ".local/models.json"))
    config = load_models()
    assert config["models"]["kimi"]["token_budget"] == 700000
    assert Path(config["ledger_directory"]) == tmp_path / ".local/model-usage"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-only")
    assert get_key(config, "deepseek") == "fixture-only"
    with pytest.raises(ValueError, match="already exists"):
        script.setup("bob", 500000, 700000, root=tmp_path)


def fixture_record(uid, kind):
    return {"uid": uid, "type": kind, "timestamps": [],
            "haystack_session": [[{"role": "user", "content": "I live in Seattle. I like books."}],
                                 [{"role": "user", "content": "I now live in Austin."}]],
            "M_old": "I live in Seattle.", "M_new": "I now live in Austin.",
            "explanation": "relocated", "relevant_session_index": [0, 1],
            "probing_queries": {"dim3_query": "What utilities should I use?"}}


def schema_fixture(schema):
    if schema.get("type") == "object":
        return {k: schema_fixture(v) for k, v in schema["properties"].items()}
    if schema.get("type") == "boolean":
        return True
    return "Synthetic test output; not scientific evidence"


def fake_native(context):
    return {"tasks": {t["id"]: schema_fixture(t["schema"]) for t in context.stage["config"]["tasks"]},
            "accounting": {"charged_or_reserved": 0}}


def test_two_isolated_studies_full_flow_and_evidence_tampering(tmp_path, monkeypatch):
    source = tmp_path / "src/research_lab"
    source.mkdir(parents=True)
    for name in ("stale_packing_v5.py", "stale_retrieval.py"):
        shutil.copyfile(ROOT / "src/research_lab" / name, source / name)
    dataset = tmp_path / "dataset.json"
    write_json(dataset, [fixture_record("one", "T1"), fixture_record("two", "T2")])
    monkeypatch.setattr(study_adapters, "run_metered", lambda context, tasks:
        ({t["id"]: schema_fixture(t["schema"]) for t in tasks}, {"charged_or_reserved": 0}, "synthetic-only"))
    registry = {**adapters(), "native_tasks": Adapter(fake_native, paid=True)}
    roots = []
    for name in ("alice-memory", "bob-memory"):
        initialize(name, dataset, readers_per_type=1, root=tmp_path)
        project = Project(tmp_path / "projects" / name, registry)
        roots.append(project.root)
        # Local advance may reach the first gate but cannot run paid stages.
        state = project.advance()
        assert state["stages"][1]["attempts"] == 0
        for _ in range(15):
            state = project.advance(allow_models=True)
            if state["status"] == "completed":
                break
            pending = [s for s in state["stages"] if s["status"] == "awaiting_review"]
            assert pending, state
            for stage in pending:
                packet = project.review_packet(stage["id"])
                project.decide(stage["id"], "accept", "fixture-validator", "Synthetic isolated handoff test", packet["binding"])
        assert project.status()["status"] == "completed"
        assert len(list(project.root.rglob("paper_draft.md"))) == 1
        state = read_json(project.path)
        dataset_paths = {v["dataset"]["path"] for v in state["inputs"].values() if "dataset" in v}
        assert len(dataset_paths) == 1  # Large dataset copied once per project.
    first = Project(roots[0], registry)
    second = Project(roots[1], registry)
    before = second.path.read_bytes()
    record = read_json(first.path)["stages"]["retrieval"]["attempts"][-1]
    result = read_json(first.root / record["result_path"])
    attachment = first.root / result["artifacts"][0]["path"]
    attachment.write_text("tampered", "utf-8")
    assert first.status()["stages"][3]["status"] == "stale"
    assert second.status()["status"] == "completed"
    assert second.path.read_bytes() == before
    with pytest.raises(ValueError, match="exists"):
        initialize("alice-memory", dataset, readers_per_type=1, root=tmp_path)


def test_share_scanner_blocks_secret_and_nested_submission():
    scan = load_script("check_share")
    assert scan.issues("submissions/round5/team.zip", b"dummy")
    assert scan.issues("src/config.py", ("sk-" + "a" * 40).encode())
    assert not scan.issues(".env.example", b"DEEPSEEK_API_KEY=replace-locally")
    assert not scan.issues("config/projects/threshold.json", b"{}")
