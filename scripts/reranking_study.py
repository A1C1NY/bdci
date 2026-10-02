"""Initialize or inspect a bounded offline study with explicit scientific review gates."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_lab.project import Project
from research_lab.reranking_study import registry
from research_lab.storage import digest, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["init", "status", "advance", "review", "decide"])
    p.add_argument("--project", required=True)
    p.add_argument("--dataset")
    p.add_argument("--model-directory", default=str(ROOT / ".local/models/ms-marco-MiniLM-L6-v2"))
    p.add_argument("--stage")
    p.add_argument("--binding")
    p.add_argument("--action", choices=["accept", "reject", "request_changes", "terminate"])
    p.add_argument("--actor")
    p.add_argument("--reason")
    a = p.parse_args()
    project = Project(a.project, registry())
    if a.command == "init":
        if not a.dataset:
            p.error("--dataset required")
        name = project.root.name
        config_dir = ROOT / ".local/reranking-configs" / name
        if project.root.exists() or config_dir.exists():
            raise ValueError("Existing study is immutable; use a new project directory")
        dataset = Path(a.dataset).resolve()
        write_json(config_dir / "dataset.json", {"path": str(dataset), "sha256": digest(dataset)})
        protocol = {"question": "Does learned relevance reranking retain more updated-state evidence under a fixed context budget?",
                    "data_exposure": "All 400 STALE scenarios previously used. Retrospective diagnostic, not unseen evaluation.",
                    "primary": "ce_32 minus bm25_32 at 1024 reference WordPiece tokens, scenario-clustered mean of three queries",
                    "secondary": "window versus whole-turn packing; candidate truncation loss; 512/2048 reference tokens",
                    "budgets": [512, 1024, 2048], "candidate_k": 32, "window_radius": 1,
                    "methods": ["bm25_all", "bm25_32", "ce_32", "bm25_window_32", "ce_window_32"],
                    "inference": "Official quantized MiniLM-L6 cross encoder, CPU; pair max length 256; batch 8; threads 4",
                    "statistics": "10000 paired scenario bootstrap replicates, seed 20260930; secondary intervals descriptive",
                    "no_adaptive_selection": True, "no_reader_claims": True, "model_token_limit": 0}
        write_json(config_dir / "protocol.json", protocol)
        sources = [{"path": str(ROOT / "src/research_lab" / n), "sha256": digest(ROOT / "src/research_lab" / n)}
                   for n in ("neural_retrieval.py", "reranking_study.py", "stale_retrieval.py", "stale_packing_v5.py")]
        config = {"schema_version": 5, "id": name, "question": protocol["question"], "model_token_limit": 0,
                  "stages": [{"id": "brief", "adapter": "artifact", "role": "proposal", "inputs": {"protocol": "protocol.json"}},
                             {"id": "freeze", "adapter": "artifact", "role": "freeze", "needs": ["brief"], "inputs": {"protocol": "protocol.json"}},
                             {"id": "retrieval", "adapter": "local_reranking_retrieval", "needs": ["freeze"], "inputs": {"dataset_manifest": "dataset.json"},
                              "config": {"model_directory": str(Path(a.model_directory).resolve()), "cache_directory": str(ROOT / ".local/reranker-cache"),
                                         "threads": 4, "budgets": protocol["budgets"], "sources": sources}},
                             {"id": "analysis", "adapter": "local_reranking_analysis", "role": "interpretation", "needs": ["retrieval"]}]}
        write_json(config_dir / "project.json", config)
        result = project.initialize(config_dir / "project.json")
    elif a.command == "status": result = project.status()
    elif a.command == "advance": result = project.advance()
    elif a.command == "review": result = project.review_packet(a.stage)
    else:
        if not all((a.stage, a.action, a.actor, a.reason, a.binding)):
            p.error("decide needs stage, action, actor, reason and current review binding")
        result = project.decide(a.stage, a.action, a.actor, a.reason, a.binding)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
