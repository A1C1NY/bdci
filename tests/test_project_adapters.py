import json
from pathlib import Path

import pytest

from research_lab.project import Context, Project
from research_lab.project_adapters import (comparison, evidence_report, literature_cards,
                                           literature_search, native_tasks, proposal, tabular_experiment)
from research_lab.storage import read_json, write_json


def ctx(tmp_path, config=None, inputs=None, deps=None):
    return Context(tmp_path, {"config": config or {}}, inputs or {}, deps or {}, "local-fixture")


def test_evidence_calculates_from_fields_and_rejects_missing_reference(tmp_path):
    context = ctx(tmp_path, {"claims": [{"id": "gain", "operation": "difference",
        "sources": [{"stage": "a", "pointer": "/score"}, {"stage": "b", "pointer": "/score"}]}]},
        deps={"a": {"score": 0.8}, "b": {"score": 0.3}})
    result = evidence_report(context)
    assert result["claims"][0]["value"] == 0.5
    assert result["semantic_review"] == "requires_supervisor"
    context.dependencies.pop("b")
    with pytest.raises(KeyError):
        evidence_report(context)


def test_literature_requires_exact_excerpt_without_claiming_entailment(tmp_path):
    path = tmp_path / "text.txt"
    path.write_text("A local source excerpt.", encoding="utf-8")
    card = {"id": "a", "input": "source", "title": "fixture", "url": "local:source",
            "locator": "line 1", "excerpt": "source excerpt", "supported_statement": "claim"}
    context = ctx(tmp_path, {"cards": [card]}, {"source": path})
    assert literature_cards(context)["cards"][0]["entailment"] == "requires_supervisor"
    card["excerpt"] = "fabricated quotation"
    with pytest.raises(ValueError, match="absent"):
        literature_cards(context)


def test_discovery_metadata_is_not_full_text(monkeypatch, tmp_path):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            return json.dumps({"message": {"items": [{"title": ["Fixture"], "DOI": "10.fixture/example"}]}}).encode()
    def fetch(request, timeout):
        assert request.full_url.startswith("https://api.crossref.org/works?")
        assert timeout == 25
        return Response()
    monkeypatch.setattr("research_lab.project_adapters.urlopen", fetch)
    result = literature_search(ctx(tmp_path, {"query": "agent memory"}))
    assert result["evidence_status"] == "discovery_metadata_only"


def test_candidate_bounds_and_duplicate_rejection(tmp_path):
    cfg = {"hypothesis": "test", "parent": "base", "falsifier": "no gain", "expected_effect": "gain",
           "evidence_refs": ["base"], "changes": {"parameter": 1},
           "change_schema": {"type": "object", "properties": {"parameter": {"type": "number", "maximum": 2}}, "additionalProperties": False}}
    context = ctx(tmp_path, cfg, deps={"base": {"score": 0}})
    first = proposal(context)
    context.dependencies["previous"] = first
    with pytest.raises(ValueError, match="Duplicate"):
        proposal(context)
    cfg["changes"]["parameter"] = 3
    with pytest.raises(Exception, match="maximum"):
        proposal(context)


def test_comparison_requires_matched_data_and_metrics(tmp_path):
    row = {"dataset_sha256": "a", "metric": "accuracy", "direction": "maximize", "split": "development", "n": 4, "metrics": {"score": 0.5}}
    context = ctx(tmp_path, {"baseline": "b", "candidate": "c"}, deps={"b": row, "c": {**row, "metrics": {"score": 0.75}}})
    assert comparison(context)["gain"] == 0.25
    context.dependencies["c"]["dataset_sha256"] = "different"
    with pytest.raises(ValueError, match="Unmatched"):
        comparison(context)


def test_native_bridge_preserves_stage_cap_and_never_passes_raw_inputs(monkeypatch, tmp_path):
    import research_lab.native_research as native
    import research_lab.framework as framework
    monkeypatch.setattr(framework, "ROOT", tmp_path)
    calls = []
    def run(stage, tasks, **kwargs):
        calls.append((stage, tasks, kwargs))
        return {"task": {"answer": "fixture"}}
    monkeypatch.setattr(native, "run_tasks", run)
    context = ctx(tmp_path, {"tasks": [{"id": "task", "phase": "test", "model": "deepseek", "prompt": "bounded", "schema": {"type": "object"}}]}, deps={"approved": {"summary": "safe"}})
    context.stage["token_limit"] = 200000
    native_tasks(context)
    assert calls[0][2]["stage_limit"] == 200000
    assert "safe" in calls[0][1][0]["prompt"]
    context.inputs["dataset"] = tmp_path / "never-read.json"
    with pytest.raises(ValueError, match="raw dataset"):
        native_tasks(context)
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["threshold", "linear"])
def test_two_configurations_complete_with_same_engine(tmp_path, name):
    root = Path(__file__).resolve().parents[1]
    project = Project(tmp_path / name)
    project.initialize(root / "config/projects" / (name + ".json"))
    for _ in range(8):
        status = project.advance()
        if status["status"] == "completed":
            break
        for stage in status["stages"]:
            if stage["status"] == "awaiting_review":
                packet = project.review_packet(stage["id"])
                if stage["id"] == "freeze":
                    assert packet["result"]["meets_rule"]
                project.decide(stage["id"], "accept", "fixture-validator", "known fixture", packet["binding"])
        project = Project(project.root)
    assert project.status()["status"] == "completed"
    assert project.status()["model_tokens_charged_or_reserved"] == 0
    assert all(s["attempts"] == 1 for s in project.advance()["stages"])


def test_overlapping_data_split_rejected(tmp_path):
    write_json(tmp_path / "data.json", [{"id": "same", "x": 1, "y": 1}])
    config = {"schema_version": 5, "id": "overlap", "question": "test", "stages": [
        {"id": "dev", "adapter": "tabular_experiment", "inputs": {"dataset": "data.json"}},
        {"id": "freeze", "adapter": "artifact", "role": "freeze", "needs": ["dev"]},
        {"id": "holdout", "adapter": "tabular_experiment", "split": "holdout", "needs": ["freeze"], "inputs": {"dataset": "data.json"}}]}
    write_json(tmp_path / "config.json", config)
    with pytest.raises(ValueError, match="overlap"):
        Project(tmp_path / "project").initialize(tmp_path / "config.json")
