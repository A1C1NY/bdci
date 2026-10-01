"""Create isolated, supervised STALE replications; not an autonomous discovery loop."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from .project import Project, contained
from .storage import digest, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]


def manuscript_draft(context):
    """Retain model draft and linked evidence for supervisor editing, never publish."""
    draft = context.dependencies["draft"]["tasks"]["paper-prose"]
    evidence = context.dependencies["analysis"]
    base = contained(context.root, "evidence/" + context.run_id)
    base.mkdir(parents=True, exist_ok=True)
    paragraphs = ["# " + draft["title"],
                  "> Unreviewed model draft. Check every claim and add verified sources, methods and tables before submission."]
    for key in ("abstract", "introduction", "discussion", "limitations"):
        paragraphs += ["## " + key.title(), draft[key]]
    target = base / "paper_draft.md"
    target.write_text("\n\n".join(paragraphs) + "\n", "utf-8")
    write_json(base / "evidence.json", evidence)
    return {"artifacts": [{"path": p.relative_to(context.root).as_posix(), "sha256": digest(p)}
                          for p in (target, base / "evidence.json")],
            "ready_for_submission": False, "requires": ["supervisor editing", "verified references", "ICLR PDF", "matching review token", "competition packaging"]}


def initialize(name, dataset, *, readers_per_type=2, seed="team-pilot-1", root=ROOT):
    root = Path(root).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Use a unique member-topic ID with letters, digits, _ or -")
    if not 1 <= readers_per_type <= 32:
        raise ValueError("readers_per_type must be 1..32")
    project = root / "projects" / name
    config_dir = root / ".local" / "study-configs" / name
    if project.exists() or config_dir.exists():
        raise ValueError("Study ID exists; never reuse or reset completed research")
    records = read_json(dataset)
    if not isinstance(records, list) or not records:
        raise ValueError("Expected a nonempty STALE dataset list")
    ids = [r["uid"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Dataset UIDs must be unique")
    selected = []
    for kind in sorted({r["type"] for r in records}):
        group = sorted((r for r in records if r["type"] == kind),
                       key=lambda r: hashlib.sha256((seed + ":" + r["uid"]).encode()).hexdigest())
        if len(group) < readers_per_type:
            raise ValueError("Not enough scenarios in a category")
        selected.extend(r["uid"] for r in group[:readers_per_type])
    config_dir.mkdir(parents=True)
    shutil.copyfile(dataset, config_dir / "dataset.json")
    hashes = {"src/research_lab/" + name: digest(root / "src/research_lab" / name)
              for name in ("stale_packing_v5.py", "stale_retrieval.py")}
    protocol = {"question": "Does sentence-level versus turn-level BM25 packing change update evidence and reader answers?",
                "study_type": "replication_pilot_not_new_discovery", "dataset_sha256": digest(dataset),
                "n_scenarios": len(records), "reader_uids": selected, "seed": seed,
                "primary": "sentence_bm25 minus turn_bm25 at 4096 UTF-8 history bytes",
                "limitations": ["Known previously used dataset; not a fresh blind test", "Lexical evidence metric", "Model judges, no human validation", "Pilot sample; no novelty claim"],
                "source_hashes": hashes, "oracle": "Disabled in this team starter"}
    write_json(config_dir / "protocol.json", protocol)
    string = {"type": "string"}
    schema = {"type": "object", "properties": {"assessment": string, "recommendation": string},
              "required": ["assessment", "recommendation"], "additionalProperties": False}
    common = {"source_hashes": hashes}
    def task(sid, prompt, output_schema=schema):
        return {"id": sid, "phase": sid, "model": "kimi", "prompt": prompt, "schema": output_schema}
    stages = [
        {"id": "brief", "adapter": "artifact", "role": "proposal", "inputs": {"protocol": "protocol.json"}},
        {"id": "design", "adapter": "native_tasks", "role": "proposal", "needs": ["brief"], "token_limit": 300000,
         "config": {"tasks": [task("design-review", "Audit the supplied replication protocol. Identify confounds and required checks. Do not invent novelty or completed experiments. Keep below 400 words.")]}},
        {"id": "freeze", "adapter": "artifact", "role": "freeze", "needs": ["design"], "inputs": {"protocol": "protocol.json"}},
        {"id": "retrieval", "adapter": "stale_v5_retrieval", "needs": ["freeze"], "inputs": {"dataset": "dataset.json"}, "config": common},
        {"id": "readers", "adapter": "stale_v5_readers", "needs": ["freeze"], "inputs": {"dataset": "dataset.json"},
         "token_limit": len(selected) * 4 * 140000, "max_attempts": 1,
         "config": {**common, "reader_uids": selected, "oracle_uids": []}},
        {"id": "judges", "adapter": "stale_v5_judges", "needs": ["readers"], "inputs": {"dataset": "dataset.json"},
         "token_limit": len(selected) * 2 * 140000, "max_attempts": 1, "config": common},
        {"id": "analysis", "adapter": "stale_v5_analysis", "role": "interpretation", "needs": ["retrieval", "readers", "judges"], "inputs": {"dataset": "dataset.json"}, "config": common},
        {"id": "interpretation", "adapter": "native_tasks", "role": "interpretation", "needs": ["analysis"], "token_limit": 300000,
         "config": {"tasks": [task("evidence-review", "Audit these actual results, missingness, uncertainty and limitations. Distinguish replication from novelty; never invent evidence. Keep below 500 words.")]}},
        {"id": "draft", "adapter": "native_tasks", "role": "interpretation", "needs": ["analysis", "interpretation"], "token_limit": 300000,
         "config": {"tasks": [task("paper-prose", "Write concise English prose grounded only in supplied evidence. Preserve null/negative results and limitations. Do not invent sources, novelty, methods or statistical significance. Abstract <=180 words; other sections <=350 words.",
             {"type": "object", "properties": {k: string for k in ("title", "abstract", "introduction", "discussion", "limitations")},
              "required": ["title", "abstract", "introduction", "discussion", "limitations"], "additionalProperties": False})]}},
        {"id": "manuscript", "adapter": "manuscript_draft", "role": "interpretation", "needs": ["analysis", "draft"]}]
    config = {"schema_version": 5, "id": name, "question": protocol["question"],
              "model_token_limit": sum(s.get("token_limit", 0) for s in stages), "stages": stages}
    write_json(config_dir / "project.json", config)
    return Project(project).initialize(config_dir / "project.json")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--id", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--readers-per-type", type=int, default=2)
    p.add_argument("--seed", default="team-pilot-1")
    a = p.parse_args()
    print(json.dumps(initialize(a.id, a.dataset, readers_per_type=a.readers_per_type, seed=a.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
