"""Trusted offline experiment adapter: candidate/ranking/packing decomposition."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

from .project import Adapter, Project, contained
from .stale_retrieval import public_view, normalize
from .stale_packing_v5 import interval, token_inclusion
from .storage import digest, read_json, write_json, utc_now


def run_retrieval(context):
    from .neural_retrieval import LocalReranker, contexts
    cfg = context.stage["config"]
    data = read_json(context.inputs["dataset_manifest"])
    source = Path(data["path"])
    if digest(source) != data["sha256"]:
        raise ValueError("Frozen external dataset changed")
    for item in cfg["sources"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("Frozen experiment source changed")
    records = read_json(source)
    engine = LocalReranker(cfg["model_directory"], cfg["cache_directory"], threads=cfg["threads"])
    base = contained(context.root, "evidence/" + context.run_id)
    base.mkdir(parents=True, exist_ok=True)
    rows, diagnostics, artifacts = [], [], []
    started = time.monotonic()
    for index, record in enumerate(records):
        for dim, query in record["probing_queries"].items():
            packed, detail = contexts(public_view(record), query, engine, tuple(cfg["budgets"]))
            old, new = normalize(record["M_old"]), normalize(record["M_new"])
            for item in packed:
                rows.append({"uid": record["uid"], "type": record["type"], "dim": dim,
                             "method": item["method"], "budget": item["budget"], "units": item["units"],
                             "new": int(new in normalize(item["context"])),
                             "old": int(old in normalize(item["context"])),
                             "token_new": int(token_inclusion(record["M_new"], item["context"])),
                             "selected": item["selected"], "context_sha256": hashlib.sha256(item["context"].encode()).hexdigest()})
            diagnostics.append({"uid": record["uid"], "dim": dim,
                                "candidate_update": any(new in normalize(t) for t in detail["candidate_texts"]),
                                "window_update": any(new in normalize(t) for t in detail["candidate_windows"]),
                                "candidate_count": len(detail["candidates"]),
                                "truncation_risk_count": sum(n + detail["query_reference_length"] + 3 > 256 for n in detail["candidate_reference_lengths"])})
            key = hashlib.sha256((record["uid"] + ":" + dim).encode()).hexdigest()
            path = base / "contexts" / (key + ".json")
            write_json(path, {"uid": record["uid"], "dim": dim, "query": query, "contexts": packed, "diagnostics": detail})
            artifacts.append({"path": path.relative_to(context.root).as_posix(), "sha256": digest(path)})
        progress = {"completed_scenarios": index + 1, "total_scenarios": len(records),
                    "local_inference_pairs": engine.pairs, "local_inference_seconds": engine.inference_seconds,
                    "cache_hits": engine.cache_hits, "wall_seconds": time.monotonic() - started, "updated_at": utc_now()}
        write_json(base / "progress.json", progress)
        if (index + 1) % 10 == 0:
            print(json.dumps(progress), flush=True)
    for name, values in (("rows", rows), ("diagnostics", diagnostics)):
        path = base / (name + ".json")
        write_json(path, values)
        artifacts.append({"path": path.relative_to(context.root).as_posix(), "sha256": digest(path)})
    return {"n_scenarios": len(records), "n_rows": len(rows), "engine": engine.identity,
            "resource": progress, "gateway_model_calls": 0, "artifacts": artifacts,
            "scientific_status": "retrospective_diagnostic_not_new_blind_evaluation"}


def dependency_file(context, name):
    item = next(x for x in context.dependencies["retrieval"]["artifacts"] if x["path"].endswith("/" + name + ".json"))
    path = contained(context.root, item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError("Retrieval evidence changed")
    return path


def summarize(rows, diagnostics):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[(row["method"], row["budget"])][row["uid"]].append(row)
    summaries = []
    for (method, budget), scenarios in sorted(grouped.items()):
        values = {metric: interval([sum(r[metric] for r in values) / len(values) for values in scenarios.values()])
                  for metric in ("new", "old", "token_new", "units")}
        summaries.append({"method": method, "budget": budget, **values})
    contrasts = [("ce_32", "bm25_32"), ("ce_window_32", "ce_32"),
                 ("bm25_window_32", "bm25_32"), ("bm25_32", "bm25_all")]
    paired = []
    for treatment, control in contrasts:
        for budget in sorted({r["budget"] for r in rows}):
            a, b = grouped[(treatment, budget)], grouped[(control, budget)]
            if set(a) != set(b):
                raise ValueError("Unpaired scenario sets")
            values = [sum(r["new"] for r in a[uid]) / len(a[uid]) - sum(r["new"] for r in b[uid]) / len(b[uid]) for uid in sorted(a)]
            paired.append({"treatment": treatment, "control": control, "budget": budget, **interval(values)})
    return {"summary": summaries, "paired": paired,
            "primary": next(r for r in paired if r["treatment"] == "ce_32" and r["control"] == "bm25_32" and r["budget"] == 1024),
            "diagnostics": {"queries": len(diagnostics),
                            "candidate_update_rate": sum(r["candidate_update"] for r in diagnostics) / len(diagnostics),
                            "window_update_rate": sum(r["window_update"] for r in diagnostics) / len(diagnostics),
                            "truncation_risk_count": sum(r["truncation_risk_count"] for r in diagnostics),
                            "candidate_count": sum(r["candidate_count"] for r in diagnostics)},
            "limitations": ["STALE data reused; not a fresh blind test", "Literal and token-contiguous metrics are not semantic entailment",
                            "WordPiece is a fixed reference tokenizer, not the actual reader tokenizer", "Quantized MS MARCO relevance model, not a temporal-validity classifier",
                            "Model pair input truncated at 256 tokens", "No reader answer or human-judged gains established by this offline stage"]}


def analyze(context):
    report = summarize(read_json(dependency_file(context, "rows")), read_json(dependency_file(context, "diagnostics")))
    target = contained(context.root, "evidence/" + context.run_id + "/analysis.json")
    write_json(target, report)
    return {**report, "artifacts": [{"path": target.relative_to(context.root).as_posix(), "sha256": digest(target)}]}


def registry():
    from .project_adapters import adapters
    return {**adapters(), "local_reranking_retrieval": Adapter(run_retrieval), "local_reranking_analysis": Adapter(analyze)}
