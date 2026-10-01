"""Supervised research projects: versioned DAGs, durable attempts and decisions.

Adapters are trusted Python registered by the host, never imported from model output.
The single atomic state record is authoritative; attempts and decisions are retained.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import re
import time

import jsonschema

from .storage import digest, read_json, run_lock, utc_now, write_json


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def contained(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes project: " + str(name))
    return path


@dataclass
class Adapter:
    run: object
    paid: bool = False
    network: bool = False

    def fingerprint(self):
        source = inspect.getsourcefile(self.run)
        return {"name": self.run.__module__ + "." + self.run.__qualname__,
                "source": digest(source) if source else identity(inspect.getsource(self.run))}


@dataclass
class Context:
    root: Path
    stage: dict
    inputs: dict
    dependencies: dict
    run_id: str


def validate(config, registry):
    if config.get("schema_version") != 5:
        raise ValueError("Expected project schema_version 5")
    for key in ("id", "question"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError("Missing " + key)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", config["id"]):
        raise ValueError("Invalid project id")
    if type(config.get("model_token_limit", 0)) is not int or config.get("model_token_limit", 0) < 0:
        raise ValueError("Invalid model_token_limit")
    stages = config.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("Project needs stages")
    seen = set()
    for stage in stages:
        sid = stage.get("id", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", sid) or sid in seen:
            raise ValueError("Invalid or duplicate stage id")
        if stage.get("adapter") not in registry:
            raise ValueError("Unknown trusted adapter")
        needs = stage.get("needs", [])
        if not isinstance(needs, list) or len(set(needs)) != len(needs) or any(n not in seen for n in needs):
            raise ValueError("Stages must be topologically ordered with unique dependencies")
        if type(stage.get("review", True)) is not bool:
            raise ValueError("review must be boolean")
        if stage.get("role") in ("proposal", "freeze", "interpretation") and not stage.get("review", True):
            raise ValueError("Scientific decisions require supervisor review")
        if type(stage.get("max_attempts", 2)) is not int or stage.get("max_attempts", 2) < 1:
            raise ValueError("Invalid max_attempts")
        if stage.get("split", "development") not in ("development", "holdout"):
            raise ValueError("Invalid split")
        if stage.get("split") == "holdout":
            gates = [s for s in stages if s["id"] in needs and s.get("role") == "freeze" and s.get("review", True)]
            if not gates:
                raise ValueError("Holdout requires a reviewed freeze dependency")
        if stage.get("role") in ("proposal", "literature"):
            ancestors = set(needs)
            for s in reversed(stages[:len(seen)]):
                if s["id"] in ancestors:
                    ancestors.update(s.get("needs", []))
            if any(s.get("split") == "holdout" and s["id"] in ancestors for s in stages):
                raise ValueError("Development/proposal cannot depend on holdout results")
        cap = stage.get("token_limit", 0)
        if type(cap) is not int or cap < 0 or (registry[stage["adapter"]].paid and cap == 0):
            raise ValueError("Paid stages need a positive token_limit")
        jsonschema.Draft202012Validator.check_schema(stage.get("output_schema", {"type": "object"}))
        seen.add(sid)
    return config


class Project:
    def __init__(self, root, registry=None):
        self.root = Path(root).resolve()
        if registry is None:
            from .project_adapters import adapters
            registry = adapters()
        self.registry = registry
        self.path = self.root / "project-state.json"

    def _save(self, state):
        state["updated_at"] = utc_now()
        write_json(self.path, state)

    def _event(self, state, kind, **fields):
        state["events"].append({"time": utc_now(), "kind": kind, **fields})

    def _snapshot_config(self, path, revision):
        path = Path(path).resolve()
        config = validate(read_json(path), self.registry)
        inputs = {}
        for stage in config["stages"]:
            inputs[stage["id"]] = {}
            for key, name in stage.get("inputs", {}).items():
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", key):
                    raise ValueError("Invalid input id")
                source = contained(path.parent, name)
                if not source.is_file():
                    raise ValueError("Missing input " + name)
                target = self.root / "inputs" / "blobs" / digest(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if digest(target) != target.name:
                        raise ValueError("Existing input snapshot changed")
                else:
                    import shutil
                    shutil.copyfile(source, target)
                inputs[stage["id"]][key] = {"path": target.relative_to(self.root).as_posix(), "sha256": digest(target)}
        groups = {"development": set(), "holdout": set()}
        for stage in config["stages"]:
            if stage["adapter"] == "tabular_experiment":
                rows = read_json(contained(self.root, inputs[stage["id"]]["dataset"]["path"]))
                groups[stage.get("split", "development")].update(r["id"] for r in rows)
        if groups["development"] & groups["holdout"]:
            raise ValueError("Development and holdout observation IDs overlap")
        return config, inputs

    def initialize(self, config_path):
        self.root.mkdir(parents=True, exist_ok=True)
        with run_lock(self.root):
            if self.path.exists() or any(p.name != ".run.lock" for p in self.root.iterdir()):
                raise ValueError("New project directory must be empty")
            config, inputs = self._snapshot_config(config_path, 1)
            state = {"schema_version": 5, "config": config, "inputs": inputs, "revision": 1,
                     "config_history": [{"revision": 1, "config": config, "inputs": inputs}],
                     "stages": {s["id"]: {"status": "pending", "attempts": []} for s in config["stages"]},
                     "decisions": [], "events": [], "terminated": False, "holdout_exposed": False,
                     "model_tokens_charged_or_reserved": 0, "created_at": utc_now()}
            self._event(state, "initialized")
            self._save(state)
        return self.status()

    def _signature(self, state, stage):
        inputs = state["inputs"][stage["id"]]
        for item in inputs.values():
            if digest(contained(self.root, item["path"])) != item["sha256"]:
                raise ValueError("Input snapshot changed")
        deps = {}
        for sid in stage.get("needs", []):
            record = state["stages"][sid]
            if record["status"] != "accepted":
                raise ValueError("Dependency not accepted: " + sid)
            deps[sid] = record["attempts"][-1]["result_sha256"]
        return identity({"stage": stage, "inputs": inputs, "dependencies": deps,
                         "adapter": self.registry[stage["adapter"]].fingerprint(), "engine": digest(__file__)})

    def _refresh(self, state):
        for stage in state["config"]["stages"]:
            record = state["stages"][stage["id"]]
            if record["status"] not in ("accepted", "awaiting_review"):
                continue
            last = record["attempts"][-1]
            try:
                valid = (last["signature"] == self._signature(state, stage) and
                         digest(contained(self.root, last["result_path"])) == last["result_sha256"])
                if valid:
                    result = read_json(contained(self.root, last["result_path"]))
                    for item in result.get("artifacts", []):
                        if digest(contained(self.root, item["path"])) != item["sha256"]:
                            valid = False
            except (ValueError, OSError, KeyError):
                valid = False
            if not valid:
                record["status"] = "stale"
                self._event(state, "invalidated", stage=stage["id"], reason="Inputs, dependencies, adapter or output changed")

    def _read(self):
        state = read_json(self.path)
        validate(state["config"], self.registry)
        self._refresh(state)
        return state

    def status(self):
        # Read-only projection. It detects stale artifacts without modifying the project.
        state = self._read()
        rows = []
        for stage in state["config"]["stages"]:
            record = state["stages"][stage["id"]]
            blockers = [n for n in stage.get("needs", []) if state["stages"][n]["status"] != "accepted"]
            rows.append({"id": stage["id"], "adapter": stage["adapter"], "needs": stage.get("needs", []),
                         "status": record["status"], "blocked_by": blockers,
                         "attempts": len(record["attempts"]),
                         "last_error": record["attempts"][-1].get("error") if record["attempts"] else None})
        status = "terminated" if state["terminated"] else "completed" if all(r["status"] == "accepted" for r in rows) else "awaiting_supervisor" if any(r["status"] in ("awaiting_review", "rejected", "stale", "failed", "running", "changes_requested") for r in rows) else "ready"
        return {"id": state["config"]["id"], "question": state["config"]["question"], "revision": state["revision"],
                "status": status, "stages": rows, "decisions": state["decisions"], "events": state["events"][-30:],
                "holdout_exposed": state["holdout_exposed"],
                "model_tokens_charged_or_reserved": state["model_tokens_charged_or_reserved"],
                "model_token_limit": state["config"].get("model_token_limit", 0),
                "scientific_success_not_implied": True}

    def advance(self, *, allow_models=False, allow_network=False):
        with run_lock(self.root):
            state = self._read()
            if state["terminated"]:
                raise ValueError("Project terminated")
            self._save(state)
            for stage in state["config"]["stages"]:
                record = state["stages"][stage["id"]]
                if record["status"] != "pending":
                    continue
                if any(state["stages"][n]["status"] != "accepted" for n in stage.get("needs", [])):
                    continue
                adapter = self.registry[stage["adapter"]]
                if adapter.paid and not allow_models:
                    continue
                if adapter.network and not allow_network:
                    continue
                if len(record["attempts"]) >= stage.get("max_attempts", 2):
                    raise ValueError("Stage attempt limit exhausted")
                signature = self._signature(state, stage)
                reserve = stage.get("token_limit", 0) if adapter.paid else 0
                if state["model_tokens_charged_or_reserved"] + reserve > state["config"].get("model_token_limit", 0):
                    raise ValueError("Project model budget exhausted")
                state["model_tokens_charged_or_reserved"] += reserve
                attempt_id = len(record["attempts"]) + 1
                attempt = {"id": attempt_id, "revision": state["revision"], "signature": signature,
                           "started_at": utc_now(), "tokens_charged_or_reserved": reserve}
                record["attempts"].append(attempt)
                record["status"] = "running"
                if stage.get("split") == "holdout":
                    state["holdout_exposed"] = True
                self._event(state, "started", stage=stage["id"], attempt=attempt_id)
                self._save(state)  # Durable intent before any adapter or paid call.
                start = time.monotonic()
                try:
                    dependencies = {n: read_json(contained(self.root, state["stages"][n]["attempts"][-1]["result_path"])) for n in stage.get("needs", [])}
                    inputs = {k: contained(self.root, v["path"]) for k, v in state["inputs"][stage["id"]].items()}
                    run_id = identity(str(self.root))[:12] + "-" + stage["id"] + "-" + str(attempt_id)
                    result = adapter.run(Context(self.root, deepcopy(stage), inputs, dependencies, run_id))
                    jsonschema.validate(result, stage.get("output_schema", {"type": "object"}))
                    result_path = self.root / "artifacts" / stage["id"] / str(attempt_id) / "result.json"
                    write_json(result_path, result)
                    attempt.update(result_path=result_path.relative_to(self.root).as_posix(), result_sha256=digest(result_path))
                    actual = result.get("accounting", {}).get("charged_or_reserved") if adapter.paid else 0
                    if type(actual) is int and actual > reserve:
                        state["model_tokens_charged_or_reserved"] += actual - reserve
                        attempt["tokens_charged_or_reserved"] = actual
                        raise ValueError("Adapter exceeded its declared reservation")
                    if type(actual) is int and 0 <= actual <= reserve:
                        state["model_tokens_charged_or_reserved"] -= reserve - actual
                        attempt["tokens_charged_or_reserved"] = actual
                    record["status"] = "awaiting_review" if stage.get("review", True) else "accepted"
                except BaseException as exc:
                    record["status"] = "failed"
                    attempt["error"] = type(exc).__name__ + ": " + str(exc)
                    raise
                finally:
                    attempt.update(finished_at=utc_now(), wall_seconds=time.monotonic() - start)
                    self._event(state, "attempt_finished", stage=stage["id"], status=record["status"])
                    self._save(state)
        return self.status()

    def review_packet(self, sid):
        state = self._read()
        record = state["stages"][sid]
        if record["status"] != "awaiting_review":
            raise ValueError("Stage is not awaiting review")
        attempt = record["attempts"][-1]
        return {"project": state["config"]["id"], "stage": sid,
                "binding": identity({"signature": attempt["signature"], "result": attempt["result_sha256"], "attempt": attempt["id"], "protocol": state["config"]}),
                "protocol": state["config"],
                "stage_spec": next(s for s in state["config"]["stages"] if s["id"] == sid),
                "result": read_json(contained(self.root, attempt["result_path"])),
                "checks": {"output_schema": "passed", "artifact_integrity": "passed", "scientific_validity": "requires_supervisor"}}

    def decide(self, sid, action, actor, reason, binding):
        if action not in ("accept", "reject", "request_changes", "terminate") or not actor.strip() or not reason.strip():
            raise ValueError("Decision requires action, actor and reason")
        with run_lock(self.root):
            packet = self.review_packet(sid)
            if binding != packet["binding"]:
                raise ValueError("Review binding changed; read a fresh packet")
            state = self._read()
            state["decisions"].append({"stage": sid, "action": action, "actor": actor, "reason": reason,
                                       "binding": binding, "time": utc_now()})
            state["stages"][sid]["status"] = {"accept": "accepted", "reject": "rejected", "request_changes": "changes_requested", "terminate": "rejected"}[action]
            if action == "terminate":
                state["terminated"] = True
            self._event(state, "decision", stage=sid, action=action)
            self._save(state)
        return self.status()

    def retry(self, sid, actor, reason):
        if not actor.strip() or not reason.strip():
            raise ValueError("Retry needs actor and reason")
        with run_lock(self.root):
            state = self._read()
            stage = next(s for s in state["config"]["stages"] if s["id"] == sid)
            record = state["stages"][sid]
            if state["terminated"] or record["status"] not in ("failed", "running", "changes_requested", "rejected", "stale"):
                raise ValueError("Stage cannot be retried")
            if stage.get("split") == "holdout" and record["attempts"]:
                raise ValueError("No selective holdout retry; preserve failures and create a new protocol")
            if len(record["attempts"]) >= stage.get("max_attempts", 2):
                raise ValueError("Stage attempt limit exhausted")
            record["status"] = "pending"
            self._event(state, "retry_authorized", stage=sid, actor=actor, reason=reason)
            self._refresh(state)
            self._save(state)
        return self.status()

    def revise(self, config_path, actor, reason):
        if not actor.strip() or not reason.strip():
            raise ValueError("Revision needs actor and reason")
        with run_lock(self.root):
            state = self._read()
            if state["terminated"] or state["holdout_exposed"]:
                raise ValueError("Terminated/exposed project is immutable; create a new protocol")
            new = validate(read_json(config_path), self.registry)
            if new["id"] != state["config"]["id"] or [s["id"] for s in new["stages"]] != [s["id"] for s in state["config"]["stages"]]:
                raise ValueError("Revision must retain project and stage identities")
            old = {s["id"]: s for s in state["config"]["stages"]}
            revision = state["revision"] + 1
            config, inputs = self._snapshot_config(config_path, revision)
            changed = set()
            for stage in config["stages"]:
                sid = stage["id"]
                old_hashes = {k: v["sha256"] for k, v in state["inputs"][sid].items()}
                new_hashes = {k: v["sha256"] for k, v in inputs[sid].items()}
                if (old[sid] != stage or old_hashes != new_hashes or
                    (stage.get("role") == "freeze" and config != state["config"]) or
                    any(n in changed for n in stage.get("needs", []))):
                    changed.add(sid)
                    state["stages"][sid]["status"] = "pending"
                else:
                    inputs[sid] = state["inputs"][sid]
            state.update(config=config, inputs=inputs, revision=revision)
            state["config_history"].append({"revision": revision, "config": config, "inputs": inputs})
            self._event(state, "revised", actor=actor, reason=reason, invalidated=sorted(changed))
            self._save(state)
        return self.status()
