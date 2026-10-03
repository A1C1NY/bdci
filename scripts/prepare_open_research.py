"""Prepare a private broad-brief campaign from explicit local asset manifests."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_lab.storage import read_json, write_json


def prepare(brief, asset_paths, source_path, output, budgets, provider="crossref", hours=6):
    target = Path(output).resolve()
    if target.exists():
        raise ValueError("Choose a new private configuration path")
    if not 10 <= len(brief) <= 4000 or min(budgets.values()) <= 0 or not 1 <= hours <= 168:
        raise ValueError("Explicit brief, positive model budgets and bounded hours required")
    assets = []
    for name in asset_paths:
        path = Path(name).resolve()
        item = read_json(path)
        if item.get("data_exposure") == "synthetic_fixture":
            raise ValueError("Use the fixture command for synthetic assets")
        for key in ("training", "development", "evaluation"):
            if key in item:
                item[key] = str((path.parent / item[key]).resolve())
                if not Path(item[key]).is_file():
                    raise ValueError("Missing registered data split")
        assets.append(item)
    sources = []
    if source_path:
        path = Path(source_path).resolve()
        for item in read_json(path):
            item["path"] = str((path.parent / item["path"]).resolve())
            if not Path(item["path"]).is_file():
                raise ValueError("Missing source snapshot")
            sources.append(item)
    if provider == "local" and not sources:
        raise ValueError("Local literature mode requires source snapshots")
    config = {"version": 1, "brief": brief, "fixture": False, "literature_provider": provider,
        "search_results": 6, "max_topic_rounds": 3, "resources": ["cpu"], "assets": assets, "sources": sources,
        "min_gain": .01, "max_candidates": 5, "patience": 3, "max_review_revisions": 2,
        "max_model_calls": 80, "max_wall_seconds": hours * 3600, "max_local_seconds": 1800,
        "roles": {"director": "kimi", "writer": "kimi", "reviewers": ["deepseek", "kimi"]},
        "model_budget": budgets, "compile_pdf": False}
    write_json(target, config)
    return target


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brief", required=True)
    p.add_argument("--asset", action="append", required=True, help="Local JSON asset manifest; repeat for additional datasets")
    p.add_argument("--sources", help="Optional local JSON array of id/title/url/path/evidence_level")
    p.add_argument("--literature", choices=["crossref", "arxiv", "local"], default="crossref")
    p.add_argument("--output", required=True)
    p.add_argument("--deepseek-budget", required=True, type=int)
    p.add_argument("--kimi-budget", required=True, type=int)
    p.add_argument("--hours", type=int, default=6)
    a = p.parse_args()
    print(prepare(a.brief, a.asset, a.sources, a.output,
                  {"deepseek": a.deepseek_budget, "kimi": a.kimi_budget}, a.literature, a.hours))
