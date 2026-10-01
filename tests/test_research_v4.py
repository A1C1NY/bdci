import asyncio
import hashlib
import json
from pathlib import Path
import pytest
from research_lab.stale_retrieval import Retriever, public_view, validate_policy, BASELINES
from research_lab.native_research import ENGINE, MeteredBackend, parse_object
from jiuwenswarm.common.research_runtime import evidence_gate


def test_selector_never_needs_labels_and_honors_bytes():
    record={"uid":"x","haystack_session":[[{"role":"user","content":"I used to run."}],
            [{"role":"user","content":"Now my knee hurts; no more running."}]],
            "timestamps":[],"probing_queries":{},"M_new":"secret","explanation":"secret"}
    view=public_view(record)
    assert "M_new" not in view and "explanation" not in view
    selected=Retriever(view).select("running",BASELINES[0],90)
    assert selected["bytes"]==len(selected["context"].encode())<=90
    assert "secret" not in selected["context"]


@pytest.mark.parametrize("value",[float("nan"),float("inf"),-1,2,True,"0.5"])
def test_untrusted_policy_values_rejected(value):
    with pytest.raises(ValueError):
        validate_policy(dict(BASELINES[0],change=value))


def test_claim_gate_detects_modified_evidence(tmp_path):
    p=tmp_path/"evidence"; p.write_text("original")
    evidence={"e":{"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}}
    assert evidence_gate([{"id":"c","evidence_ids":["e"]}],evidence)
    p.write_text("modified")
    with pytest.raises(ValueError): evidence_gate([{"id":"c","evidence_ids":["e"]}],evidence)


def test_native_engine_resume_has_no_second_backend_call(tmp_path):
    class Counting(ENGINE.AgentBackend):
        calls=0
        async def run(self,prompt,opts,schema_json,**kw):
            self.calls+=1
            return ENGINE.AgentResult(text="real engine, synthetic backend",tokens=0)
    script=tmp_path/"flow.py"
    script.write_text('from swarmflow import agent\nMETA={"name":"test"}\nasync def run(args):\n    return await agent(args["prompt"])\n')
    backend=Counting(); journal=str(tmp_path/"journal.json")
    events=[]
    for i in range(2):
        result=asyncio.run(ENGINE.run_workflow(str(script),args={"prompt":"one"},backend=backend,
                journal_path=journal,resume=journal if i else None,progress_sink=events.append))
        assert result=="real engine, synthetic backend"
    assert backend.calls==1
    assert any(e.kind=="workflow_completed" for e in events)
    asyncio.run(ENGINE.run_workflow(str(script),args={"prompt":"changed"},backend=backend,
                journal_path=journal,resume=journal))
    assert backend.calls==2
