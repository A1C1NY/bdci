"""Create disclosed development/evaluation snapshots for an autonomous STALE run."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_lab.storage import read_json, write_json
from research_lab.autonomy_domains import validate_records


def prepare(dataset, source_registry, output, deepseek_budget, kimi_budget):
    target = Path(output).resolve()
    if target.exists():
        raise ValueError("Existing configuration is immutable; choose a new output")
    if min(deepseek_budget, kimi_budget) <= 0:
        raise ValueError("Provide explicitly allocated positive budgets")
    records = read_json(dataset)
    validate_records("stale_retrieval", records)
    development, evaluation = [], []
    for kind in sorted({r["type"] for r in records}):
        group = sorted((r for r in records if r["type"] == kind),
                       key=lambda r: hashlib.sha256(("autonomous-v1:" + r["uid"]).encode()).hexdigest())
        if len(group) < 2:
            raise ValueError("Each type needs at least two records")
        development.extend(group[:len(group) // 2])
        evaluation.extend(group[len(group) // 2:])
    registry_path = Path(source_registry).resolve()
    sources = read_json(registry_path)
    if not isinstance(sources, list) or not sources:
        raise ValueError("Source registry must be a nonempty array")
    for item in sources:
        item["path"] = str((registry_path.parent / item["path"]).resolve())
        if not Path(item["path"]).is_file():
            raise ValueError("Missing approved source snapshot")
    config = {"version": 1, "domain": "stale_retrieval",
        "question": "Can bounded relevance, recency and change-cue weighting improve literal update retention on STALE?",
        "development": "development.json", "evaluation": "evaluation.json", "data_exposure": "reused",
        "sources": sources, "baseline": {"relevance": 1.0, "recency": 0.0, "change": 0.0},
        "context_bytes": 4096, "min_gain": .01, "max_candidates": 3, "patience": 2,
        "max_review_revisions": 2, "max_model_calls": 40, "max_wall_seconds": 21600,
        "max_local_seconds": 3600, "roles": {"director": "kimi", "writer": "kimi", "reviewers": ["deepseek", "kimi"]},
        "model_budget": {"deepseek": deepseek_budget, "kimi": kimi_budget}, "compile_pdf": False}
    target.mkdir(parents=True)
    write_json(target / "development.json", development)
    write_json(target / "evaluation.json", evaluation)
    write_json(target / "config.json", config)
    print(target / "config.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--sources", required=True, help="JSON array of id,title,url,path for approved source texts")
    p.add_argument("--output", required=True)
    p.add_argument("--deepseek-budget", required=True, type=int)
    p.add_argument("--kimi-budget", required=True, type=int)
    a = p.parse_args()
    prepare(a.dataset, a.sources, a.output, a.deepseek_budget, a.kimi_budget)
