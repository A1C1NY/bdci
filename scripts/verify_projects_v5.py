"""Exercise two explicitly synthetic configurations; never call models or search.

The fixture validator acknowledges review packets for these known fixtures only.
Its decisions are labelled fixture-validator, never represented as human research review.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_lab.project import Project
from research_lab.storage import read_json, write_json


def verify(destination):
    records = []
    for name in ("threshold", "linear"):
        config = ROOT / "config/projects" / (name + ".json")
        assert read_json(config)["fixture_only"] is True
        project = Project(Path(destination) / ("fixture-" + name))
        project.initialize(config)
        for _ in range(8):
            status = project.advance()
            if status["status"] == "completed":
                break
            pending = [s for s in status["stages"] if s["status"] == "awaiting_review"]
            assert pending, status
            for stage in pending:
                packet = project.review_packet(stage["id"])
                if stage["id"] == "freeze":
                    assert packet["result"]["meets_rule"] is True
                project.decide(stage["id"], "accept", "fixture-validator",
                               "Known deterministic fixture; acceptance tests orchestration only.", packet["binding"])
            project = Project(project.root)  # Simulated session handoff after each gate.
        assert project.status()["status"] == "completed"
        before = project.path.read_bytes()
        assert all(s["attempts"] == 1 for s in project.advance()["stages"])
        # The state timestamp may update; no adapter repeats and results remain identical.
        records.append({"project": str(project.root), "status": project.status(),
                        "no_repeated_attempts": True})
    report = {"valid": True, "fixture_only": True, "model_calls": 0, "network_calls": 0,
              "projects": records, "limits": "Proves configuration reuse and review/resume plumbing, not cross-domain scientific ability."}
    write_json(Path(destination) / "verification-v5.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "projects"))
    args = parser.parse_args()
    result = verify(args.output)
    print({"valid": result["valid"], "projects": len(result["projects"]), "model_calls": 0})
