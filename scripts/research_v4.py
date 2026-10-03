"""Supervised stages. Commands deliberately separate development from heldout."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json, write_json, digest, utc_now
from research_lab.stale_retrieval import BASELINES, evaluate
from research_lab.native_research import run_tasks

BASE=ROOT/"research/v4"


def object_schema(fields):
    return {"type":"object", "properties":fields,"required":list(fields),"additionalProperties":False}


STR={"type":"string"}
STRINGS={"type":"array","items":STR}
REVIEW=object_schema({"assessment":STR,"closest_work":STRINGS,"threats":STRINGS,
                     "required_controls":STRINGS,"reject_claims":STRINGS})
POLICY=object_schema({"name":STR, "relevance":{"type":"number","minimum":0,"maximum":1},
                     "recency":{"type":"number","minimum":0,"maximum":1},
                     "change":{"type":"number","minimum":0,"maximum":1}})
PROPOSAL=object_schema({"hypothesis":STR,"policy":POLICY,"falsifier":STR,"limitations":STRINGS})


def data(split):
    ids=set(read_json(BASE/"split.json")[split])
    return [r for r in read_json(BASE/"assets/stale/T1_T2_400_FULL.json") if r["uid"] in ids]


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[(r["policy"],r["budget"],r["type"],r["query"])].append(r)
    return [{"policy":k[0],"budget":k[1],"type":k[2],"query":k[3],"n":len(v),
        **{field:sum(r[field] for r in v)/len(v) for field in ("old_present","new_present","new_session_present","bytes")}}
        for k,v in sorted(groups.items())]


def literature():
    sources=[("stale","https://arxiv.org/html/2605.06527v1"),
             ("tangle","https://arxiv.org/html/2608.13921v1"),
             ("trace","https://arxiv.org/html/2609.33517v1")]
    registry=[]
    for key,url in sources:
        path=BASE/"literature"/(key+".html")
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            with urllib.request.urlopen(url,timeout=60) as response:
                path.write_bytes(response.read())
        registry.append({"id":key,"url":url,"retrieved_at":utc_now(),
                         "path":str(path.relative_to(ROOT)),"sha256":digest(path)})
    write_json(BASE/"literature/registry.json",registry)


def development():
    records=data("development")
    rows=evaluate(records,BASELINES)
    write_json(BASE/"dev-baseline-rows.json",rows)
    summary=summarize(rows)
    write_json(BASE/"dev-baseline-summary.json",summary)
    brief="""Supervisor direction: an empirical audit of update-evidence loss under byte-bounded user-turn retrieval on STALE. NOT a new memory architecture and NOT CUPMem reproduction. STALE/CUPMem already studies outdated and implicitly invalidated memory, write-time invalidation and premise verification. TANGLE separates oracle curated vs extracted memory; TRACE reasons about return-conditioned memory validity. Reject the earlier proposed novelty claim 'new memory invalidation by tombstones' as already known. Proposed narrower question: Does adding query-independent recency/change cues improve access to the verbatim new-state statement at equal UTF-8 byte budgets, and does any retrieval gain transfer to an independent reader? All turns are raw user turns, with role filtering, no gold extraction. BM25, pure recent, BM25+0.25 recency are baselines. Gold M_new substring containment measures evidence availability, NOT answering quality. 80 scenario development / 320 sealed heldout. Budgets 4096/8192 bytes including turn headers. Full official benchmark uses richer full conversation context, so no leaderboard comparisons. Plan paired scenario bootstrap; no treating three correlated queries as independent. Models lack browsing; use supplied literature only.\nDevelopment aggregate:\n"""
    brief+=json.dumps(summary)
    tasks=[{"id":"novelty-review","phase":"Literature and novelty gate","model":"kimi","schema":REVIEW,"prompt":brief+"\nReview novelty, baseline fairness and threats. Keep under 650 words."},
           {"id":"candidate-1","phase":"Failure-driven proposal","model":"deepseek","schema":PROPOSAL,"prompt":brief+"\nPropose ONE limited change to bm25_recent: keep relevance=1 and recency=0.25; choose a change-cue weight between 0 and 1, name change_candidate. Change cue is a regex for now/anymore/no longer/instead/since/recently/changed/switched/started/stopped/quit/moved/new/but/however/actually. No new code or holdout access. Identify a falsifier and confounds. Return policy as numeric fields."}]
    print(json.dumps(run_tasks("development-design",tasks),ensure_ascii=True),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=["literature","development"])
    args=parser.parse_args()
    globals()[args.stage]()
