"""Persistent cross-run token admission, exact reported usage and unknown holds."""

from contextlib import contextmanager
from pathlib import Path
import time
import uuid

from .storage import read_json, run_lock, utc_now, write_json, write_text


class TokenBudgetExceeded(RuntimeError):
    pass


def normalize_usage(value, api_format):
    if not isinstance(value, dict):
        return None
    names = ("prompt_tokens", "completion_tokens") if api_format == "chat" else ("input_tokens", "output_tokens")
    input_tokens, output_tokens = (value.get(name) for name in names)
    if any(type(x) is not int or x < 0 for x in (input_tokens, output_tokens)):
        return None
    total = value.get("total_tokens", input_tokens + output_tokens)
    if type(total) is not int or total < 0:
        return None
    input_details = value.get("prompt_tokens_details" if api_format == "chat" else "input_tokens_details") or {}
    output_details = value.get("completion_tokens_details" if api_format == "chat" else "output_tokens_details") or {}
    cached = input_details.get("cached_tokens", value.get("prompt_cache_hit_tokens", 0))
    reasoning = output_details.get("reasoning_tokens", 0)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": max(total, input_tokens + output_tokens),
            "cached_input_tokens": cached if type(cached) is int and 0 <= cached <= input_tokens else 0,
            "reasoning_output_tokens": reasoning if type(reasoning) is int and 0 <= reasoning <= output_tokens else 0}


class TokenLedger:
    def __init__(self, config):
        self.root = Path(config["ledger_directory"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity = {alias: {"model": item["model"], "base_url": item["base_url"], "limit": item["token_budget"]}
                         for alias, item in config["models"].items()}
        with self.lock():
            path = self.root / "ledger.json"
            marker = self.root / "initialized.txt"
            if not path.exists():
                if marker.exists():
                    raise ValueError("Token ledger is missing; refusing to reset existing budget")
                write_text(marker, "Do not delete the ledger or reset budgets between runs.\n")
                write_json(path, {"schema_version": 1, "created_at": utc_now(), "models": self.identity,
                                  "blocked": [], "requests": []})
            self.read()

    @contextmanager
    def lock(self):
        deadline = time.monotonic() + 10
        while True:
            context = run_lock(self.root)
            try:
                context.__enter__()
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.03)
        try:
            yield
        finally:
            context.__exit__(None, None, None)

    def read(self):
        value = read_json(self.root / "ledger.json")
        if value.get("schema_version") != 1 or value.get("models") != self.identity or not isinstance(value.get("requests"), list):
            raise ValueError("Token ledger identity/limits changed; refusing automatic reset")
        return value

    @staticmethod
    def summarize(value):
        models = {}
        for alias, info in value["models"].items():
            rows = [item for item in value["requests"] if item["alias"] == alias]
            known = [item["usage"] for item in rows if item.get("usage") is not None]
            used = sum(x["total_tokens"] for x in known)
            held = sum(x["reserved_tokens"] for x in rows if x.get("usage") is None)
            models[alias] = {**info, "reported_tokens": used,
                "input_tokens": sum(x["input_tokens"] for x in known), "output_tokens": sum(x["output_tokens"] for x in known),
                "cached_input_tokens": sum(x["cached_input_tokens"] for x in known),
                "reasoning_output_tokens": sum(x["reasoning_output_tokens"] for x in known),
                "held_tokens": held, "remaining_admissible_tokens": max(0, info["limit"] - used - held),
                "requests": len(rows), "active_requests": sum(x["status"] == "active" for x in rows),
                "unknown_requests": sum(x["status"] == "unknown" for x in rows),
                "blocked": alias in value["blocked"]}
        return {"updated_at": utc_now(), "models": models,
                "recent_requests": [{key: item.get(key) for key in
                   ("id", "alias", "purpose", "status", "started_at", "finished_at", "usage", "reserved_tokens", "visible_characters", "error", "response_model", "api_format")}
                                    for item in value["requests"][-30:]],
                "note": "Reported usage updates when returned by gateway; pending/unknown calls retain conservative reservations. Cached/reasoning fields are subsets, not extra tokens."}

    def snapshot(self):
        with self.lock():
            return self.summarize(self.read())

    def reserve(self, alias, amount, *, purpose, api_format):
        if type(amount) is not int or amount <= 0:
            raise ValueError("Invalid reservation")
        with self.lock():
            value = self.read()
            summary = self.summarize(value)["models"][alias]
            if summary["blocked"] or summary["remaining_admissible_tokens"] < amount:
                raise TokenBudgetExceeded(f"{alias}: token budget cannot admit this request")
            request_id = uuid.uuid4().hex
            value["requests"].append({"id": request_id, "alias": alias, "purpose": purpose,
                 "api_format": api_format, "reserved_tokens": amount, "status": "active",
                 "usage": None, "started_at": utc_now(), "visible_characters": 0})
            write_json(self.root / "ledger.json", value)
            return request_id

    def progress(self, request_id, characters):
        with self.lock():
            value = self.read()
            row = next(item for item in value["requests"] if item["id"] == request_id)
            row["visible_characters"] = characters
            write_json(self.root / "ledger.json", value)

    def finish(self, request_id, usage, *, error=None, response_model=None):
        with self.lock():
            value = self.read()
            row = next(item for item in value["requests"] if item["id"] == request_id)
            if row["status"] != "active":
                raise ValueError("Request already settled")
            row.update(usage=usage, status="settled" if usage is not None else "unknown",
                       finished_at=utc_now(), error=error, response_model=response_model)
            if usage is not None and usage["total_tokens"] > row["reserved_tokens"]:
                value["blocked"] = sorted(set(value["blocked"]) | {row["alias"]})
                row["error"] = "Gateway usage exceeded reserved bound; route blocked for review"
            write_json(self.root / "ledger.json", value)
            return dict(row)
