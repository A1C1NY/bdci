"""One explicit supervisor-authorized recovery; retains failed request accounting."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.native_research import run_tasks
from research_lab.storage import read_json,write_json
from research_v4 import BASE,object_schema,STR,STRINGS
section=object_schema({"heading":STR,"paragraphs":STRINGS,"evidence_ids":STRINGS})
write_json(BASE/"writing-recovery.json",{"supervisor":"Codex","decision":"One new bounded request for missing methods/protocol only",
    "reason":"Original method call timed out; native SwarmFlow returned None. Successful framing/findings reused unchanged. Unknown gateway reservation retained.","not_scientific_retry":True})
prompt="""Write two English research sections, about 300 words each. JSON fields method and protocol; each has heading, paragraphs, evidence_ids. Evidence IDs: protocol, retrieval, paired. Do not invent references or experiments. Study: sparse raw-user-turn retrieval on public STALE, not a novel memory architecture. Index only user turns, no gold states or gold session IDs. Whole turns are greedily packed under exact 4096/8192 UTF-8 bytes including [session s, turn t] headers, then ordered chronologically. BM25 tokenization lowercase alphanumeric, fixed English stopwords, k1=1.2,b=.75, query tokens unique. Per-query relevance scores normalized by maximum. Score = normalized BM25 + alpha * i/max(1,N-1) + beta * binary change regex (now, anymore, no longer, instead, since, recently, changed, switched, started, stopped, quit, moved, new, but, however, actually). Ties prefer later turn. Baselines pure BM25, pure recent, BM25 alpha=.25 beta=0. Candidates proposed by DeepSeek from development diagnostics: alpha=.25 beta=.1 retained; alpha=.75 beta=0 rejected. Candidate acceptance >=1 percentage point gain at 4096 bytes and <=3 points loss per query dimension over temporal baseline. Frozen prior to heldout. Public data 400 scenarios, UID-hash split80dev320heldout with all3queries clustered. Primary metric normalized verbatim M_new containment, NOT answer correctness. Some states may not occur verbatim. 10000 paired scenario bootstrap resamples with seed20260929, primary comparison selected vsBM25 at4096; others descriptive. Reader pilot: first24 frozen heldout hashes, 2 models, 2 policies, 3 queries =288 calls. No gold/method name exposed to reader. Opposite-model judge grades3answers using original STALE rubric. Missing requests reported, no selective scientific retry. Not official full-context STALE score. Pipeline uses native openJiuwen SwarmFlow with typed tasks, persistent budgets and human/Codex supervision. Model cannot run arbitrary code; only bounded policy DSL. Do not claim general safety or full product deployment."""
result=run_tasks("paper-method-recovery-001",[{"id":"method","phase":"Explicit writing recovery","model":"deepseek","schema":object_schema({"method":section,"protocol":section}),"prompt":prompt}])
old=read_json(ROOT/"outputs/v4-paper-core/results.json")
old["method"]=result["method"]
assert all(isinstance(v,dict) for v in old.values()),"Writing still incomplete"
write_json(BASE/"model-sections-core.json",{k:v for g in old.values() for k,v in g.items()})
print("Recovered manuscript sections without reissuing completed tasks")
