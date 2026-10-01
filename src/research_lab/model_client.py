"""OpenAI-compatible Chat/Responses transport, with metering before every attempt."""

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request

from .model_config import get_key
from .token_ledger import TokenLedger, normalize_usage


class ModelRequestError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def redact(text, key=""):
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)


def response_text(value):
    if isinstance(value.get("output_text"), str):
        return value["output_text"]
    return "".join(part.get("text", "") for item in value.get("output", [])
                   if item.get("type") == "message" for part in item.get("content", [])
                   if part.get("type") == "output_text")


def stream_events(response, deadline):
    data, total = [], 0
    for raw in response:
        total += len(raw)
        if total > 16 * 1024 * 1024:
            raise ModelRequestError("Response exceeded 16 MiB transport limit")
        if time.monotonic() > deadline:
            raise TimeoutError("Model request deadline exceeded")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                value = "\n".join(data)
                data = []
                if value == "[DONE]":
                    return
                yield json.loads(value)
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))


class ModelClient:
    def __init__(self, config, *, notify=None):
        self.config = config
        self.ledger = TokenLedger(config)
        self.notify = notify or self.console
        # The gateway is explicitly configured; do not forward credentials through ambient proxies or redirects.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def console(self, alias, stage, **fields):
        info = self.ledger.snapshot()["models"][alias]
        print(f"[{alias} {stage}] reported={info['reported_tokens']:,} "
              f"held={info['held_tokens']:,} limit={info['limit']:,} "
              f"remaining={info['remaining_admissible_tokens']:,}", file=sys.stderr, flush=True)

    def generate(self, alias, messages, *, purpose="manual", max_output_tokens=None, api_format=None, stream=None):
        model = self.config["models"][alias]
        stream = model.get("stream", True) if stream is None else stream
        if type(stream) is not bool:
            raise ValueError("stream must be a boolean")
        key = get_key(self.config, alias)
        api_format = api_format or model["api_format"]
        if api_format not in ("chat", "responses"):
            raise ValueError("Unsupported API format")
        # Text only for now: image token upper bounds depend on the gateway's vision implementation.
        if (not isinstance(messages, list) or not messages or any(
            not isinstance(item, dict) or set(item) != {"role", "content"}
            or item["role"] not in ("system", "user", "assistant") or not isinstance(item["content"], str)
            for item in messages)):
            raise ValueError("Expected nonempty text messages with role/content")
        prompt_bytes = json.dumps(messages, ensure_ascii=False).encode("utf-8")
        if len(prompt_bytes) > model["max_input_bytes"]:
            raise ValueError("Input exceeds configured byte allowance; no request sent")
        maximum = model["max_output_tokens"] if max_output_tokens is None else max_output_tokens
        if type(maximum) is not int or not 0 < maximum <= model["max_output_tokens"]:
            raise ValueError("Output limit exceeds route configuration")
        if api_format == "chat":
            payload = {"model": model["model"], "messages": messages, "max_tokens": maximum, "stream": stream}
            if stream:
                payload["stream_options"] = {"include_usage": True}
            endpoint = "chat/completions"
        else:
            payload = {"model": model["model"], "input": messages, "max_output_tokens": maximum,
                       "stream": stream, "store": False}
            endpoint = "responses"
        request = urllib.request.Request(model["base_url"].rstrip("/") + "/" + endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                     "Accept": "text/event-stream" if stream else "application/json"})
        for attempt in range(model["max_attempts"]):
            request_id = self.ledger.reserve(alias, model["input_token_reservation"] + maximum,
                                             purpose=purpose, api_format=api_format)
            self.notify(alias, "started", request_id=request_id)
            chunks, usage, reported_model = [], None, None
            terminal, finish_reason, characters, last_update = False, None, 0, 0
            start = time.monotonic()
            settled = False
            try:
                with self.opener.open(request, timeout=model["timeout_seconds"]) as response:
                    is_stream = "text/event-stream" in response.headers.get("Content-Type", "")
                    if is_stream:
                        for item in stream_events(response, start + model["timeout_seconds"]):
                            if "error" in item:
                                raise ModelRequestError("Gateway stream error: " + redact(str(item["error"]), key)[:400])
                            delta = ""
                            if api_format == "chat":
                                reported_model = item.get("model", reported_model)
                                if item.get("usage") is not None:
                                    usage = normalize_usage(item["usage"], api_format)
                                for choice in item.get("choices", []):
                                    delta += choice.get("delta", {}).get("content") or ""
                                    if choice.get("finish_reason"):
                                        terminal, finish_reason = True, choice["finish_reason"]
                            else:
                                kind = item.get("type", "")
                                if kind == "response.output_text.delta":
                                    delta = item.get("delta", "")
                                if kind in ("response.completed", "response.incomplete", "response.failed"):
                                    final = item.get("response", {})
                                    usage = normalize_usage(final.get("usage"), api_format)
                                    reported_model = final.get("model")
                                    terminal, finish_reason = True, final.get("status", kind.split(".")[-1])
                                    if not chunks:
                                        delta = response_text(final)
                            chunks.append(delta)
                            characters += len(delta)
                            if time.monotonic() - last_update >= 1:
                                self.ledger.progress(request_id, characters)
                                self.notify(alias, "streaming", visible_characters=characters)
                                last_update = time.monotonic()
                    else:
                        raw = response.read(16 * 1024 * 1024 + 1)
                        if len(raw) > 16 * 1024 * 1024:
                            raise ModelRequestError("Response exceeded transport limit")
                        value = json.loads(raw)
                        if "error" in value:
                            raise ModelRequestError("Gateway error: " + redact(str(value["error"]), key)[:400])
                        usage = normalize_usage(value.get("usage"), api_format)
                        reported_model = value.get("model")
                        if api_format == "chat":
                            choice = value.get("choices", [{}])[0]
                            chunks = [choice.get("message", {}).get("content") or ""]
                            finish_reason = choice.get("finish_reason")
                        else:
                            chunks = [response_text(value)]
                            finish_reason = value.get("status")
                        terminal = bool(finish_reason)
                text = redact("".join(chunks), key)
                # Missing completion or usage cannot silently become zero expenditure.
                if not terminal:
                    raise ModelRequestError("Stream/response ended without a terminal status")
                if text and usage and usage["total_tokens"] == 0:
                    usage = None
                self.ledger.progress(request_id, len(text))
                row = self.ledger.finish(request_id, usage, response_model=reported_model,
                                         error=None if usage else "Gateway returned no valid usage; reservation retained")
                settled = True
                self.notify(alias, "finished", usage=usage)
                if row.get("error") and "exceeded reserved" in row["error"]:
                    raise ModelRequestError(row["error"])
                return {"request_id": request_id, "alias": alias, "requested_model": model["model"],
                        "response_model": reported_model, "api_format": api_format, "text": text,
                        "usage": usage, "finish_reason": finish_reason,
                        "complete": finish_reason in ("stop", "completed"),
                        "wall_seconds": time.monotonic() - start,
                        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest()}
            except BaseException as exc:
                status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                if isinstance(exc, urllib.error.HTTPError):
                    body = exc.read(4096).decode("utf-8", errors="replace")
                    message = f"HTTP {status}: " + redact(body, key)[:400]
                elif isinstance(exc, ModelRequestError):
                    message = str(exc)
                else:
                    message = type(exc).__name__  # No credential-bearing Request repr or headers.
                if not settled:
                    self.ledger.finish(request_id, None, error=message, response_model=reported_model)
                    self.notify(alias, "unknown", error=message)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                if (status in (429, 500, 502, 503, 504) and "forbidden" not in message.lower()
                        and attempt + 1 < model["max_attempts"]):
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelRequestError(message, status=status) from None
