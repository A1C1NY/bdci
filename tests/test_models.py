from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from research_lab.model_client import ModelClient, ModelRequestError, redact
from research_lab.model_review import parse_review
from research_lab.token_ledger import TokenLedger, TokenBudgetExceeded, normalize_usage


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_KEY", "sk-testing-not-a-real-key")
    return {"ledger_directory": str(tmp_path / "ledger"), "credentials_file": str(tmp_path / "missing"),
            "roles": {"critic": "test"}, "models": {"test": {
            "model": "requested-name", "base_url": "http://127.0.0.1:1/v1", "api_key_env": "TEST_RESEARCH_KEY",
            "api_format": "chat", "token_budget": 20000, "input_token_reservation": 1000,
            "max_input_bytes": 900, "max_output_tokens": 100, "timeout_seconds": 5, "max_attempts": 2}}}


@pytest.fixture
def gateway(config):
    settings = {"status": 200, "missing_usage": False, "drop": False, "calls": [], "fail_first": False, "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            settings["calls"].append((self.path, body))
            if settings["redirect"]:
                self.send_response(307)
                self.send_header("Location", "/other")
                self.end_headers()
                return
            status = 502 if settings["fail_first"] and len(settings["calls"]) == 1 else settings["status"]
            if status != 200:
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b'{"error":"temporary failure sk-testing-not-a-real-key"}')
                return
            usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20,
                     "prompt_tokens_details": {"cached_tokens": 4}, "completion_tokens_details": {"reasoning_tokens": 3}}
            response_usage = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20,
                              "input_tokens_details": {"cached_tokens": 4}, "output_tokens_details": {"reasoning_tokens": 3}}
            if settings["missing_usage"]:
                usage = response_usage = None
            if self.path.endswith("chat/completions"):
                events = [{"model": "requested-name", "choices": [{"delta": {"content": "OK"}, "finish_reason": None}]}]
                if not settings["drop"]:
                    events += [{"choices": [{"delta": {}, "finish_reason": "stop"}]}, {"choices": [], "usage": usage}]
                final = {"model": "requested-name", "choices": [{"message": {"content": "OK", "reasoning_content": "private reasoning"}, "finish_reason": settings.get("finish_reason", "stop")}], "usage": usage}
            else:
                final = {"model": "requested-name", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}], "usage": response_usage}
                events = [{"type": "response.output_text.delta", "delta": "OK"}]
                if not settings["drop"]:
                    events.append({"type": "response.completed", "response": final})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if body["stream"] else "application/json")
            self.end_headers()
            if body["stream"]:
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(json.dumps(final).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    config["models"]["test"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield config, settings
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("api_format", ["chat", "responses"])
@pytest.mark.parametrize("stream", [True, False])
def test_both_transports_meter_real_http(gateway, api_format, stream):
    config, settings = gateway
    result = ModelClient(config, notify=lambda *a, **kw: None).generate("test", [{"role": "user", "content": "test"}], api_format=api_format, stream=stream)
    assert result["text"] == "OK" and result["complete"]
    summary = TokenLedger(config).snapshot()["models"]["test"]
    assert summary["reported_tokens"] == 20 and summary["held_tokens"] == 0
    assert summary["cached_input_tokens"] == 4 and summary["reasoning_output_tokens"] == 3
    assert settings["calls"][0][1]["model"] == "requested-name"
    assert "sk-testing" not in (Path(config["ledger_directory"]) / "ledger.json").read_text()


@pytest.mark.parametrize("drop", [False, True])
def test_missing_usage_and_disconnect_keep_reservation(gateway, drop):
    config, settings = gateway
    settings["missing_usage"], settings["drop"] = True, drop
    client = ModelClient(config, notify=lambda *a, **kw: None)
    if drop:
        with pytest.raises(ModelRequestError, match="terminal"):
            client.generate("test", [{"role": "user", "content": "test"}])
    else:
        assert client.generate("test", [{"role": "user", "content": "test"}])["usage"] is None
    info = TokenLedger(config).snapshot()["models"]["test"]
    assert info["reported_tokens"] == 0 and info["held_tokens"] == 1100 and info["unknown_requests"] == 1


def test_retry_counts_each_attempt_and_redacts_errors(gateway):
    config, settings = gateway
    settings["fail_first"] = True
    client = ModelClient(config, notify=lambda *a, **kw: None)
    client.generate("test", [{"role": "user", "content": "test"}])
    info = client.ledger.snapshot()["models"]["test"]
    assert info["requests"] == 2 and info["held_tokens"] == 1100 and info["reported_tokens"] == 20
    assert "sk-testing" not in (Path(config["ledger_directory"]) / "ledger.json").read_text()


def test_redirect_never_forwards_credentials(gateway):
    config, settings = gateway
    settings["redirect"] = True
    with pytest.raises(ModelRequestError, match="307"):
        ModelClient(config, notify=lambda *a, **kw: None).generate("test", [{"role": "user", "content": "test"}])
    assert len(settings["calls"]) == 1


def test_persistent_budget_cannot_be_reset(config):
    config["models"]["test"]["token_budget"] = 1100
    ledger = TokenLedger(config)
    ledger.reserve("test", 1100, purpose="test", api_format="chat")
    with pytest.raises(TokenBudgetExceeded):
        TokenLedger(config).reserve("test", 1, purpose="new-run", api_format="chat")
    modified = deepcopy(config)
    modified["models"]["test"]["token_budget"] = 2200
    with pytest.raises(ValueError, match="changed"):
        TokenLedger(modified)
    (Path(config["ledger_directory"]) / "ledger.json").unlink()
    with pytest.raises(ValueError, match="refusing to reset"):
        TokenLedger(config)


def test_concurrent_reservations_cannot_overspend(config):
    config["models"]["test"]["token_budget"] = 1100
    ledger = TokenLedger(config)
    def reserve():
        try:
            ledger.reserve("test", 1100, purpose="concurrent", api_format="chat")
            return True
        except TokenBudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: reserve(), range(4))) == 1


def test_gateway_overrun_blocks_future_calls(config):
    ledger = TokenLedger(config)
    rid = ledger.reserve("test", 10, purpose="test", api_format="chat")
    ledger.finish(rid, normalize_usage({"prompt_tokens": 12, "completion_tokens": 8}, "chat"))
    with pytest.raises(TokenBudgetExceeded):
        ledger.reserve("test", 1, purpose="after-overrun", api_format="chat")


def test_claim_ids_and_usage_are_not_invented():
    assert normalize_usage({"prompt_tokens": True, "completion_tokens": 8}, "chat") is None
    assert normalize_usage({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 5}, "chat")["total_tokens"] == 18
    value = {"summary": "ok", "strengths": [], "next_experiments": [], "issues": [
        {"severity": "major", "evidence_ids": ["made_up"], "problem": "x", "action": "y"}]}
    with pytest.raises(ValueError, match="unknown evidence"):
        parse_review(json.dumps(value), {"real"})
    assert "sk-testing" not in redact("error sk-testing-not-a-real-key")


def test_model_assignment_stays_pending_supervisor(config, tmp_path, monkeypatch):
    from research_lab.supervised_tasks import run_assignment
    from research_lab.storage import write_json, read_json
    assignment = {"schema_version": 1, "task_id": "bounded_test", "model_alias": "test",
        "research_question": "Fixed question", "objective": "Find one design issue",
        "boundaries": ["Do not change research topic"], "acceptance_checks": ["Supervisor checks evidence"],
        "context_files": [], "evidence_ids": ["real"], "max_output_tokens": 100}
    path = tmp_path / "task.json"
    write_json(path, assignment)
    class FakeClient:
        def __init__(self, config):
            pass
        def generate(self, alias, messages, **kwargs):
            assert kwargs["max_output_tokens"] == 100
            assert kwargs.get("stream") is None  # Respect the assigned route's default.
            return {"complete": True, "request_id": "local-test", "usage": None,
                    "text": json.dumps({"summary": "Proposal only", "strengths": [], "issues": [], "next_experiments": []})}
    monkeypatch.setattr("research_lab.supervised_tasks.ModelClient", FakeClient)
    state = run_assignment(path, tmp_path / "result", config)
    assert state["status"] == "awaiting_supervisor"
    assert state["supervisor_decision"] == "pending" and not state["applied_to_research"]
    assert read_json(path) == assignment


def test_oversized_input_never_spends(gateway):
    config, settings = gateway
    client = ModelClient(config, notify=lambda *a, **kw: None)
    with pytest.raises(ValueError, match="byte allowance"):
        client.generate("test", [{"role": "user", "content": "x" * 1000}])
    assert not settings["calls"]
    assert client.ledger.snapshot()["models"]["test"]["requests"] == 0


def test_route_default_nonstream_and_truncation_are_metered(gateway):
    config, settings = gateway
    config["models"]["test"]["stream"] = False
    client = ModelClient(config, notify=lambda *a, **kw: None)
    result = client.generate("test", [{"role": "user", "content": "test"}])
    assert result["text"] == "OK" and result["complete"]
    path, body = settings["calls"][-1]
    assert path == "/v1/chat/completions" and body["stream"] is False
    assert "stream_options" not in body and body["max_tokens"] == 100
    settings["finish_reason"] = "length"
    result = client.generate("test", [{"role": "user", "content": "test"}])
    assert not result["complete"] and result["usage"]["total_tokens"] == 20
    assert client.ledger.snapshot()["models"]["test"]["reported_tokens"] == 40
    client.generate("test", [{"role": "user", "content": "test"}], stream=True)
    assert settings["calls"][-1][1]["stream"] is True


def test_guide_environment_key_and_legacy_file_fallback(config, tmp_path, monkeypatch):
    from research_lab.model_config import get_key
    config["models"]["test"]["api_key_env"] = "DEEPSEEK_API_KEY"
    config["models"]["test"]["api_key_env_aliases"] = ["RESEARCH_DEEPSEEK_API_KEY"]
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_DEEPSEEK_API_KEY", raising=False)
    credentials = tmp_path / "credentials"
    credentials.write_text('RESEARCH_DEEPSEEK_API_KEY="legacy-test-key"\n', encoding="utf-8")
    config["credentials_file"] = str(credentials)
    assert get_key(config, "test") == "legacy-test-key"
    monkeypatch.setenv("RESEARCH_DEEPSEEK_API_KEY", "legacy-env-key")
    assert get_key(config, "test") == "legacy-env-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "guide-env-key")
    assert get_key(config, "test") == "guide-env-key"


def test_cli_respects_route_nonstream_default(gateway, monkeypatch):
    from research_lab.cli import main
    config, settings = gateway
    config["models"]["test"]["stream"] = False
    monkeypatch.setattr("research_lab.model_config.load_models", lambda path: config)
    assert main(["model-check", "--model", "test", "--max-output-tokens", "100"]) == 0
    assert settings["calls"][-1][1]["stream"] is False
