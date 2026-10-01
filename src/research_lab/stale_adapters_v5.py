"""Trusted real-research adapters for the V5 project engine; no model-generated code."""
from pathlib import Path
import json
from .project import Adapter, contained
from .storage import read_json, write_json, digest, run_lock, utc_now

ROOT = Path(__file__).resolve().parents[2]
def output_dir(context):
    base = contained(context.root, "evidence/" + context.run_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def artifact(context, dependency, name):
    items = context.dependencies[dependency]["artifacts"]
    item = next(item for item in items if Path(item["path"]).name == name + ".json")
    path = contained(context.root, item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError("Evidence artifact changed")
    return path


def verified_data(context):
    cfg = context.stage["config"]
    for name, sha in cfg["source_hashes"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != sha:
            raise ValueError("Pinned research input/source changed: " + name)
    return read_json(context.inputs["dataset"])


def receipt(context, path):
    return {"path": path.relative_to(context.root).as_posix(), "sha256": digest(path)}


def retrieval(context):
    base = output_dir(context)
    from .stale_packing_v5 import evaluate, aggregate
    records = verified_data(context)
    rows, audit, grid = evaluate(records, lambda n,total: print(f"Retrieval {n}/{total}", flush=True))
    summary = aggregate(rows, audit, grid)
    for name, value in (("retrieval-rows", rows), ("dataset-audit", audit), ("sensitivity-rows", grid), ("retrieval-summary", summary)):
        write_json(base / (name + ".json"), value)
    return {"n_scenarios": len(records), "rows": len(rows),
            "primary": next(r for r in summary["paired"] if r["method"] == "sentence_bm25" and r["budget"] == 4096),
            "summary": summary,
            "artifacts": [receipt(context, base / (n + ".json")) for n in ("retrieval-rows", "dataset-audit", "sensitivity-rows", "retrieval-summary")],
            "scientific_status": "retrospective_reuse_not_new_holdout"}


def run_metered(context, tasks):
    from .native_research import run_tasks
    lane = ROOT / ".local/v5-model-lane"
    lane.mkdir(parents=True, exist_ok=True)
    stage = "project-" + context.run_id
    with run_lock(lane):
        results = run_tasks(stage, tasks, stage_limit=context.stage["token_limit"], parallel=True, continue_on_error=True)
    directory = ROOT / "outputs" / ("v4-" + stage)
    charge = sum(read_json(p)["charged_tokens"] for p in (directory / "requests").glob("*.json"))
    return results, {"charged_or_reserved": charge}, stage


def readers(context):
    base = output_dir(context)
    from .stale_packing_v5 import make_reader_tasks
    records = verified_data(context)
    cfg = context.stage["config"]
    tasks, manifest, contexts = make_reader_tasks(records, cfg["reader_uids"], cfg["oracle_uids"])
    for name, value in (("reader-manifest", manifest), ("reader-contexts", contexts)):
        write_json(base / (name + ".json"), value)
    results, accounting, native = run_metered(context, tasks)
    write_json(base / "reader-responses.json", results)
    valid = sum(isinstance(v, dict) and "answer" in v for v in results.values())
    return {"attempted": len(tasks), "valid": valid, "failed": len(tasks)-valid,
            "native_stage": native, "accounting": accounting,
            "artifacts": [receipt(context, base / (n + ".json")) for n in ("reader-manifest", "reader-contexts", "reader-responses")]}


def judges(context):
    base = output_dir(context)
    from .stale_packing_v5 import make_judge_tasks
    records = verified_data(context)
    for item in context.dependencies["readers"]["artifacts"]:
        if digest(contained(context.root, item["path"])) != item["sha256"]:
            raise ValueError("Reader artifact changed")
    manifest = read_json(artifact(context, "readers", "reader-manifest"))
    responses = read_json(artifact(context, "readers", "reader-responses"))
    tasks, assignments = make_judge_tasks(records, manifest, responses)
    write_json(base / "judge-assignments.json", assignments)
    results, accounting, native = run_metered(context, tasks)
    write_json(base / "judge-results.json", results)
    return {"attempted": len(tasks), "native_stage": native, "accounting": accounting,
            "artifacts": [receipt(context, base / (n + ".json")) for n in ("judge-assignments", "judge-results")]}


def analysis(context):
    base = output_dir(context)
    from .stale_packing_v5 import analyze_readers
    verified_data(context)
    for dep in context.dependencies.values():
        for item in dep.get("artifacts", []):
            if digest(contained(context.root, item["path"])) != item["sha256"]:
                raise ValueError("Evidence artifact changed")
    report = analyze_readers(*[read_json(artifact(context, dep, name)) for dep, name in
                              (("readers", "reader-manifest"), ("readers", "reader-responses"),
                               ("judges", "judge-assignments"), ("judges", "judge-results"))])
    write_json(base / "reader-analysis.json", report)
    retrieval = read_json(artifact(context, "retrieval", "retrieval-summary"))
    # Compact evidence passed to model writers; full per-case records stay local.
    result = {"retrieval_primary": next(r for r in retrieval["paired"] if r["method"] == "sentence_bm25" and r["budget"] == 4096),
              "retrieval_at4096": [r for r in retrieval["summary"] if r["budget"] == 4096],
              "reader_summary": report["summary"], "reader_paired": report["paired"],
              "association": report["association"], "ceiling": retrieval["ceiling"],
              "n_scenarios": retrieval["n_scenarios"], "retrieval_rows": retrieval["retrieval_rows"],
              "reader_attempted": report["attempted"], "reader_answered": report["answered"], "reader_graded": report["graded"],
              "limitations": ["STALE replication with previously exposed data; no new unseen test set or new discovery claimed.",
                              "Fixed methods, contrasts and reader sample before new outcomes; no winner selection.",
                              "Opposite-model paired grading is fallible and not human validation; only dimension 3.",
                              "Oracle intervention uses gold only for diagnostic construction, appends evidence and is not a deployable retrieval method.",
                              "Punctuation-insensitive lexical inclusion is not semantic entailment.",
                              "One dataset; no dense pretrained retriever or learned reranker evaluated."],
              "artifacts": [receipt(context, base / "reader-analysis.json"), receipt(context, artifact(context, "retrieval", "retrieval-summary"))]}
    write_json(base / "evidence.json", result)
    return result


def registry():
    from .project_adapters import adapters
    return {**adapters(), "stale_v5_retrieval": Adapter(retrieval), "stale_v5_readers": Adapter(readers, paid=True),
            "stale_v5_judges": Adapter(judges, paid=True), "stale_v5_analysis": Adapter(analysis)}
