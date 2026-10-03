"""Bounded final critique against actual aggregate evidence."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json
from research_lab.native_research import run_tasks
from research_v4 import object_schema,STR,STRINGS

doc=read_json(ROOT/"paper/v4/document.json")
reader=read_json(ROOT/"research/v4/reader-analysis.json")
schema=object_schema({"verdict":STR,"major_issues":STRINGS,"claim_corrections":STRINGS,
                      "missing_controls":STRINGS,"submission_quality":STR})
text="""Review this competition paper against the supplied actual evidence. This is a bounded scientific audit, not official peer review. Do not invent missing numbers or demand retrospective tuning on heldout. We need accurate framing, robust missing-data handling and no novelty overclaim. The study's modest empirical contribution is accepted as scope; dense baselines/human grading remain disclosed future work, not fabricated. Identify concrete contradictions and necessary wording fixes. Keep under 800 words.\n"""
text+=json.dumps({"title":doc["title"],"abstract":doc["abstract"],
    "sections":[{"heading":s["heading"],"paragraphs":s["paragraphs"]} for s in doc["sections"]],
    "claims":doc["claims"],"reader_aggregates":reader["aggregates"],"reader_paired":reader["paired_complete"],
    "missingness":"11 reader failures. Official judge grades all 3 responses at once; any incomplete triple skipped, leaving255of288 graded. Thus22 valid answers ungraded alongside11 failed answers. No selective retries.",
    "boundary":"Native engine source-loaded; full product services not deployed. Two adjacent memory questions, not cross-domain research. Public PR user submits. New official Reviewer Token still absent."})
assert len(text.encode())<31000
result=run_tasks("final-scientific-review",[{"id":"final-review","phase":"Evidence audit","model":"kimi","schema":schema,"prompt":text}])
write_json(ROOT/"research/v4/final-model-review.json",result)
print(json.dumps(result,ensure_ascii=True))
