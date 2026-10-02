import pytest

from research_lab.neural_retrieval import bm25_scores, contexts, pack, query_window
from research_lab.reranking_study import summarize
from research_lab.stale_retrieval import Retriever, BASELINES
from research_lab.project import Context
from research_lab.reranking_study import run_retrieval, dependency_file
from research_lab.storage import digest, read_json, write_json


class FakeRanker:
    def __init__(self):
        self.seen = []

    def score(self, query, texts):
        self.seen.append((query, list(texts)))
        return list(range(len(texts)))

    def count(self, text):
        return len(text.split())


def view():
    return {"uid": "sample", "timestamps": [], "queries": {}, "sessions": [
        [{"role": "user", "content": "I like Seattle weather."}],
        [{"role": "user", "content": "I now live in Austin. My utilities changed."}],
        [{"role": "assistant", "content": "LABEL_SECRET"}]]}


def test_candidate_pool_is_shared_and_annotations_cannot_enter_ranker():
    engine = FakeRanker()
    packed, detail = contexts(view(), "weather", engine, budgets=(12, 30))
    assert len(engine.seen) == 1
    assert "LABEL_SECRET" not in str(engine.seen)
    for row in packed:
        assert row["units"] <= row["budget"]
        if row["method"] != "bm25_all":
            assert set(row["selected"]) <= set(detail["candidates"])
    leaked = {**view(), "M_new": "never expose"}
    with pytest.raises(ValueError, match="Unexpected fields"):
        contexts(leaked, "weather", engine)


def test_bm25_matches_legacy_ranking_and_zero_budget():
    retriever = Retriever(view())
    scores = bm25_scores(retriever, "Seattle weather")
    ranking = sorted(range(len(scores)), key=lambda i: (scores[i], i), reverse=True)
    old = retriever.select("Seattle weather", BASELINES[0], 80)
    new = pack(retriever.docs, ranking, 80, lambda x: len(x.encode()))
    assert new["context"] == old["context"]
    assert pack(retriever.docs, ranking, 0, len)["context"] == ""


def test_query_window_keeps_neighbors_and_is_label_independent():
    text = "First sentence. Target weather sentence. Relevant next sentence. Last sentence."
    assert query_window(text, "weather") == "First sentence. Target weather sentence. Relevant next sentence."


def test_fast_packing_matches_exact_for_separated_word_units():
    docs = Retriever(view()).docs
    for budget in range(31):
        a = pack(docs, [1, 0], budget, FakeRanker().count)
        b = pack(docs, [1, 0], budget, FakeRanker().count, additive=True)
        assert a == b


def test_paired_summary_clusters_scenarios_not_queries():
    rows = []
    for method in ("bm25_all", "bm25_32", "ce_32", "bm25_window_32", "ce_window_32"):
        for uid, count in (("one", 1), ("two", 3)):
            for _ in range(count):
                positive = int(method == "ce_32" and uid == "one")
                rows.append({"method": method, "budget": 1024, "uid": uid, "new": positive, "old": 0, "token_new": positive, "units": 5})
    diagnostics = [{"candidate_update": True, "window_update": False, "truncation_risk_count": 0, "candidate_count": 2}]
    result = summarize(rows, diagnostics)
    assert result["primary"]["n"] == 2
    assert result["primary"]["mean"] == .5
    assert result["diagnostics"]["candidate_update_rate"] == 1


def test_frozen_inputs_and_project_evidence_isolation(tmp_path, monkeypatch):
    class LocalStub(FakeRanker):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.identity = {"fixture": True}
            self.pairs = self.cache_hits = self.inference_seconds = 0
    monkeypatch.setattr("research_lab.neural_retrieval.LocalReranker", LocalStub)
    dataset = tmp_path / "data.json"
    write_json(dataset, [{"uid": "one", "type": "fixture", "M_old": "Seattle", "M_new": "Austin",
                         "haystack_session": view()["sessions"], "timestamps": [],
                         "probing_queries": {"dim3": "Where do I live?"}}])
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"path": str(dataset), "sha256": digest(dataset)})
    source = tmp_path / "implementation.py"
    source.write_text("# fixed implementation", encoding="utf-8")
    cfg = {"sources": [{"path": str(source), "sha256": digest(source)}], "model_directory": "unused",
           "cache_directory": "unused", "threads": 1, "budgets": [512, 1024, 2048]}
    first = Context(tmp_path / "first", {"config": cfg}, {"dataset_manifest": manifest}, {}, "attempt-1")
    second = Context(tmp_path / "second", {"config": cfg}, {"dataset_manifest": manifest}, {}, "attempt-1")
    a, b = run_retrieval(first), run_retrieval(second)
    assert a["n_rows"] == b["n_rows"] == 15
    assert a["gateway_model_calls"] == 0
    first.dependencies = {"retrieval": a}
    second.dependencies = {"retrieval": b}
    rows = dependency_file(first, "rows")
    rows.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        dependency_file(first, "rows")
    assert len(read_json(dependency_file(second, "rows"))) == 15
    bad = {"artifacts": [{"path": "../data.json", "sha256": digest(dataset)}]}
    first.dependencies = {"retrieval": bad}
    with pytest.raises(ValueError, match="escapes project"):
        dependency_file(first, "data")
    source.write_text("# changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        run_retrieval(second)
    dataset.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset changed"):
        run_retrieval(second)
