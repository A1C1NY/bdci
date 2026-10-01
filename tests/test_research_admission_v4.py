"""Backend hard-gate tests do not contact the gateway."""
import asyncio
from copy import deepcopy
import pytest
from research_lab.native_research import MeteredBackend, ENGINE
from research_lab.storage import read_json


class FakeClient:
    def __init__(self, fail=False):
        self.config={"models":{"deepseek":{"input_token_reservation":100,"max_output_tokens":20,"model":"test","base_url":"http://localhost"}}}
        self.calls=0;self.fail=fail
    def generate(self,*a,**kw):
        self.calls+=1
        if self.fail:raise TimeoutError()
        return {"text":'{"answer":"ok"}',"complete":True,"usage":{"total_tokens":30}}


def backend(tmp_path,client,limit):
    b=MeteredBackend(tmp_path,limit,client)
    b.bind_budget(ENGINE.BudgetLedger());b.bind_workflow_budget(ENGINE.BudgetLedger())
    return b


SCHEMA={"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"],"additionalProperties":False}


def test_admission_is_before_api_and_cache_survives_restart(tmp_path):
    c=FakeClient();b=backend(tmp_path,c,119)
    with pytest.raises(RuntimeError,match="admission"):
        asyncio.run(b.run("question",{},SCHEMA))
    assert c.calls==0
    b=backend(tmp_path,c,120)
    assert asyncio.run(b.run("question",{},SCHEMA)).structured=={"answer":"ok"}
    b=backend(tmp_path,c,120)
    assert asyncio.run(b.run("question",{},SCHEMA)).structured=={"answer":"ok"}
    assert c.calls==1
    # Completed cost 30 plus reserve 120 is above the remaining stage budget.
    with pytest.raises(RuntimeError,match="admission"):
        asyncio.run(b.run("different",{},SCHEMA))
    assert c.calls==1


def test_uncertain_request_cannot_be_automatically_reissued(tmp_path):
    c=FakeClient(True);b=backend(tmp_path,c,1000)
    with pytest.raises(TimeoutError):asyncio.run(b.run("q",{},SCHEMA))
    record=read_json(next((tmp_path/"requests").glob("*.json")))
    assert record["charged_tokens"]==120
    b=backend(tmp_path,c,1000)
    with pytest.raises(RuntimeError,match="supervisor"):
        asyncio.run(b.run("q",{},SCHEMA))
    assert c.calls==1


def test_route_change_is_not_a_backend_cache_hit(tmp_path):
    c=FakeClient();b=backend(tmp_path,c,1000)
    asyncio.run(b.run("q",{},SCHEMA))
    c.config["models"]["deepseek"]["model"]="test-v2"
    asyncio.run(b.run("q",{},SCHEMA))
    assert c.calls==2
