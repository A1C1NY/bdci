"""Deterministic development iteration and sealed retrieval evaluation."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json, write_json, digest, utc_now
from research_lab.stale_retrieval import BASELINES, Retriever, public_view, evaluate, normalize, validate_policy
from research_lab.native_research import run_tasks
from research_v4 import BASE, data, summarize, PROPOSAL


def primary(rows, name):
    relevant=[r for r in rows if r["budget"]==4096 and r["policy"]==name]
    return sum(r["new_present"] for r in relevant)/len(relevant)


def iteration():
    proposal=read_json(ROOT/"outputs/v4-development-design/results.json")["candidate-1"]
    policy=validate_policy(proposal["policy"])
    records=data("development")
    rows=evaluate(records,[policy])
    prior=read_json(BASE/"dev-baseline-rows.json")
    rows=prior+rows
    write_json(BASE/"dev-iteration-1.json",rows)
    summary=summarize(rows)
    failures=[]
    for r in records:
        q=r["probing_queries"]["dim1_query"]
        retriever=Retriever(public_view(r))
        selected=retriever.select(q,policy,4096)
        if normalize(r["M_new"]) not in normalize(selected["context"]):
            failures.append({"uid":r["uid"],"query":q,"M_new_development_label":r["M_new"],
                             "retrieved_excerpt":selected["context"][:550]})
    audit={"split":"development", "n":len(records),
           "new_statement_present_in_user_pool":sum(normalize(r["M_new"]) in normalize(" ".join(t["content"] for s in r["haystack_session"] for t in s if t["role"]=="user")) for r in records),
           "update_session_indices":dict(Counter(str(r["relevant_session_index"][-1]) for r in records)),
           "recent_baseline_explanation":"Packs the last user turns. Inserted update sessions precede trailing distractor sessions; inspect index histogram, not a broken timestamp sort. Index is given chronological session order."}
    write_json(BASE/"development-audit.json",audit)
    prompt="""One supervised development iteration. The first proposal added change-cue weight 0.1 to BM25+recency 0.25. Primary metric exact normalized new-statement containment at 4096 UTF-8 bytes; not answer quality. Diagnose supplied failures and propose ONE final single-factor change from bm25_recent (relevance=1, recency=.25, change=0): change recency only, keep change=0. Name temporal_candidate. Values [0,1]. Do not claim method novelty. No holdout labels provided. No executable code. Prior recent-only zero is explained by inserted updates followed by trailing distractors, a dataset-position limitation. We will select on development and freeze before heldout.\n"""
    prompt+=json.dumps({"primary":{p["name"]:primary(rows,p["name"]) for p in BASELINES+[policy]},"failure_examples":failures[:5],"audit":audit})
    result=run_tasks("development-iteration-2",[{"id":"candidate-2","phase":"Failure diagnosis and revision",
                     "model":"deepseek","schema":PROPOSAL,"prompt":prompt}])
    print(json.dumps(result,ensure_ascii=True))


def freeze():
    p1=read_json(ROOT/"outputs/v4-development-design/results.json")["candidate-1"]["policy"]
    p2=read_json(ROOT/"outputs/v4-development-iteration-2/results.json")["candidate-2"]["policy"]
    assert p1["relevance"]==1 and p1["recency"]==.25
    assert p2["relevance"]==1 and p2["change"]==0
    policies=BASELINES+[validate_policy(p1),validate_policy(p2)]
    rows=evaluate(data("development"),policies)
    write_json(BASE/"dev-final-rows.json",rows)
    write_json(BASE/"dev-final-summary.json",summarize(rows))
    # A proposal is retained only if >=1pp primary improvement and <=3pp loss
    # in each query dimension versus the fixed BM25+recency reference.
    baseline=primary(rows,"bm25_recent")
    decisions=[]
    eligible=[BASELINES[2]]
    for p in policies[3:]:
        delta=primary(rows,p["name"])-baseline
        dims={}
        for dim in ("dim1_query","dim2_query","dim3_query"):
            dimrows=[r for r in rows if r["query"]==dim]
            dims[dim]=primary(dimrows,p["name"])-primary(dimrows,"bm25_recent")
        accepted=delta>=.01 and min(dims.values())>=-.03
        decisions.append({"candidate":p["name"],"parent":"bm25_recent","delta":delta,"dimension_deltas":dims,
                          "decision":"retain" if accepted else "reject","reason":"Development improvement >=1pp; dimension loss <=3pp"})
        if accepted: eligible.append(p)
    winner=max(eligible,key=lambda p:primary(rows,p["name"]))
    split=read_json(BASE/"split.json")
    protocol={"version":4,"frozen_at":utc_now(),"policies":policies,"winner":winner,
              "primary":"Mean scenario-level M_new containment across all 3 queries at 4096 bytes",
              "primary_comparison":"frozen winner minus bm25; descriptive secondary versus bm25_recent",
              "secondary_budgets":[8192],"bootstrap":"10000 paired scenario resamples, seed 20260929; primary 95% percentile interval; all other intervals descriptive, no multiplicity-adjusted discoveries",
              "reader_uids":split["heldout"][:24],"reader_budget":4096,"reader_policies":["bm25",winner["name"]],
              "reader_models":["deepseek","kimi"],"reader_judge":"opposite model, official STALE rubric; pilot only, no human validation",
              "decisions":decisions,"holdout_use":"One frozen evaluation; no later tuning",
              "source_hashes":{p:digest(ROOT/p) for p in ["src/research_lab/stale_retrieval.py","scripts/evaluate_v4.py","research/v4/split.json","research/v4/assets/stale/T1_T2_400_FULL.json"]}}
    if (BASE/"frozen.json").exists(): raise RuntimeError("Protocol already frozen")
    write_json(BASE/"frozen.json",protocol)
    print(json.dumps({"winner":winner,"decisions":decisions},ensure_ascii=True))


def heldout():
    protocol=read_json(BASE/"frozen.json")
    for path,h in protocol["source_hashes"].items():
        if digest(ROOT/path)!=h: raise RuntimeError("Frozen source changed: "+path)
    rows=evaluate(data("heldout"),protocol["policies"])
    write_json(BASE/"heldout-rows.json",rows)
    summary=summarize(rows)
    write_json(BASE/"heldout-summary.json",summary)
    pairs=[]
    for budget in (4096,8192):
        for policy in protocol["policies"]:
            if policy["name"]=="bm25":continue
            for control in ("bm25","bm25_recent"):
                if policy["name"]==control:continue
                a=defaultdict(list);b=defaultdict(list)
                for r in rows:
                    if r["budget"]==budget:
                        if r["policy"]==policy["name"]:a[r["uid"]].append(r["new_present"])
                        if r["policy"]==control:b[r["uid"]].append(r["new_present"])
                dif=np.array([np.mean(a[k])-np.mean(b[k]) for k in sorted(a)])
                rng=np.random.default_rng(20260929)
                boot=np.mean(dif[rng.integers(0,len(dif),(10000,len(dif)))],axis=1)
                pairs.append({"policy":policy["name"],"control":control,"budget":budget,"n_scenarios":len(dif),"delta":float(dif.mean()),"ci95":[float(x) for x in np.quantile(boot,[.025,.975])]})
    write_json(BASE/"paired.json",pairs)
    print(json.dumps(pairs))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage",choices=["iteration","freeze","heldout"])
    globals()[p.parse_args().stage]()
