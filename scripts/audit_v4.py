"""Offline scientific replay; no network, credentials or model calls."""
from collections import Counter
from pathlib import Path
import hashlib
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,digest,utc_now
from research_lab.stale_retrieval import evaluate,Retriever,public_view,normalize


def audit():
    started=time.perf_counter();base=ROOT/"research/v4"
    protocol=read_json(base/"frozen.json")
    for path,expected in protocol["source_hashes"].items():
        assert digest(ROOT/path)==expected,"Frozen hash mismatch: "+path
    raw=read_json(base/"assets/stale/T1_T2_400_FULL.json")
    split=read_json(base/"split.json")
    assert not set(split["development"])&set(split["heldout"])
    ordered=sorted(raw,key=lambda r:hashlib.sha256(("v4-stale-20260929:"+r["uid"]).encode()).hexdigest())
    assert split["development"]==[r["uid"] for r in ordered[:80]]
    assert split["heldout"]==[r["uid"] for r in ordered[80:]]
    records=[r for r in raw if r["uid"] in set(split["heldout"])]
    actual=evaluate(records,protocol["policies"])
    assert actual==read_json(base/"heldout-rows.json"),"Offline retrieval replay differs"
    assert len(actual)==320*3*5*2
    assert all(r["bytes"]<=r["budget"] for r in actual)
    upper=sum(normalize(r["M_new"]) in normalize(" ".join(t["content"] for s in r["haystack_session"] for t in s if t["role"]=="user")) for r in records)
    # Validate every reader context against the frozen trusted selector and
    # preserve index/query association. Gold annotations are not prompt fields.
    lookup={r["uid"]:r for r in raw};retrievers={}
    manifest=read_json(base/"reader-manifest.json")
    tasks={t["id"]:t for t in read_json(ROOT/"outputs/v4-readers/input.json")["tasks"]}
    policies={p["name"]:p for p in protocol["policies"]}
    for item in manifest:
        record=lookup[item["uid"]]
        retriever=retrievers.setdefault(item["uid"],Retriever(public_view(record)))
        selected=retriever.select(record["probing_queries"][item["dim"]],policies[item["policy"]],4096)
        assert hashlib.sha256(selected["context"].encode()).hexdigest()==item["context_sha256"]
        assert selected["context"] in tasks[item["id"]]["prompt"]
        assert "M_old" not in tasks[item["id"]]["prompt"] and "Hidden Logic" not in tasks[item["id"]]["prompt"]
    result={"valid":True,"created_at":utc_now(),"wall_seconds":time.perf_counter()-started,
        "retrieval_rows_replayed":len(actual),"reader_contexts_verified":len(manifest),
        "heldout_scenarios":320,"verbatim_recoverable_scenarios":upper,
        "limits":"Hashes and deterministic replay verify provenance and arithmetic, not scientific validity or correctness of model judges."}
    write_json(base/"replay-audit.json",result)
    print(result)


if __name__=="__main__":audit()
