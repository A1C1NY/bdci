"""Generic typed prose tasks: model-written sections with approved evidence IDs."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.native_research import run_tasks
from research_lab.storage import read_json, write_json
from research_v4 import object_schema,STR,STRINGS,BASE

SECTION=object_schema({"heading":STR,"paragraphs":STRINGS,"evidence_ids":STRINGS})
fields={"abstract":SECTION,"introduction":SECTION,"related_work":SECTION,"method":SECTION,"protocol":SECTION,"retrieval_results":SECTION,"limitations":SECTION}
protocol=(BASE/"protocol.md").read_text("utf-8")
paired=read_json(BASE/"paired.json")
summary=read_json(BASE/"heldout-summary.json")
common="""Write an English research paper section, honest empirical scope, clear prose. This is a competition research manuscript, not an accepted paper. No invented citations or experiments. Known references: [stale] STALE: Can LLM Agents Know When Their Memories Are No Longer Valid?; [tangle] When Personal Memory Has No Single Answer: Evaluating LLM Agents under Irreducible Conflict; [trace] TRACE: Governing Memory Validity in Evolving Multi-Agent Systems. Use only those citation markers. Do not imply TANGLE or TRACE were reproduced. Method is an intentionally simple sparse-retrieval audit, not a new architecture. Main positive comparison is vs BM25; the change cue's incremental gain vs the temporal baseline is uncertain. Reject innovation/leaderboard superiority claims. Include negative high-recency result and pure-recency construction confound. Reader results are pending and must NOT be invented. Numerical result statements must use placeholders {{C_primary}}, {{C_incremental}}, {{C_highrecency}}, {{C_budget}} rather than writing their own numbers. Protocol constants can be written explicitly. Return each section with evidence_ids using subset of protocol, retrieval, paired, stale, tangle, trace. No Markdown headings, TeX, equations or lists inside prose paragraphs.\n"""
common+=protocol+"\nPaired results:\n"+__import__('json').dumps(paired)
groups=[("framing",["abstract","introduction","related_work"],"Write a 170-word abstract, 450-word introduction, and 350-word related work. Abstract says downstream reader evaluation is a separate diagnostic, without pretending pending results are available."),
        ("method",["method","protocol"],"Write about 600 words per section. Clearly define whole-user-turn packing, byte costs, BM25 normalization and recency/change additive score. Recency uses user-turn index divided by max(1,N-1), not wall-clock timestamps. Change feature is binary regex. Primary uncertainty resamples scenarios, not queries. Distinguish raw-turn extraction from gold-state oracle and official full-history benchmark."),
        ("findings",["retrieval_results","limitations"],"Write about 500 words per section. Carefully separate main overall gain from non-significant incremental cue gain; failed high-recency candidate and external synthetic dataset limitations. No claims about reader success yet.")]
tasks=[{"id":name,"phase":"Evidence-bound manuscript drafting","model":"deepseek",
        "schema":object_schema({k:fields[k] for k in keys}),"prompt":common+"\n"+instruction}
       for name,keys,instruction in groups]
result=run_tasks("paper-core",tasks,parallel=True)
sections={k:v for group in result.values() for k,v in group.items()}
write_json(BASE/"model-sections-core.json",sections)
print("Saved model-written sections:",list(sections))
