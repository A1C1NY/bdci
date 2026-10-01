"""Strict, human-authored Phase 1 plans; agents cannot silently change evaluation."""

import hashlib
import json
import math
from pathlib import Path
import re

from .storage import digest, read_json


def load_plan(path):
    path = Path(path).resolve()
    plan = read_json(path)
    required = {"schema_version", "title", "question", "hypothesis", "experiment",
                "methods", "baseline", "seeds", "primary_metric", "direction",
                "timeout_seconds", "max_attempts", "limitations", "references"}
    if not isinstance(plan, dict) or set(plan) != required:
        raise ValueError(f"Plan must contain exactly these fields: {sorted(required)}")
    if plan["schema_version"] != 1:
        raise ValueError("Unsupported plan schema_version")
    for key in ("title", "question", "hypothesis", "experiment", "primary_metric"):
        if not isinstance(plan[key], str) or not plan[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    methods = plan["methods"]
    if (not isinstance(methods, list) or not 2 <= len(methods) <= 10
            or any(not isinstance(x, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", x)
                   for x in methods) or len(set(methods)) != len(methods)):
        raise ValueError("methods must contain 2-10 distinct safe identifiers")
    if plan["baseline"] not in methods or plan["direction"] not in ("maximize", "minimize"):
        raise ValueError("Invalid baseline or direction")
    seeds = plan["seeds"]
    if (not isinstance(seeds, list) or not 2 <= len(seeds) <= 30
            or any(type(x) is not int or not 0 <= x < 2**31 for x in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("seeds must contain 2-30 distinct non-negative integers")
    timeout = plan["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError("timeout_seconds must be finite, in (0, 86400]")
    if type(plan["max_attempts"]) is not int or not 1 <= plan["max_attempts"] <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    if not isinstance(plan["limitations"], list) or not plan["limitations"] or any(
            not isinstance(x, str) for x in plan["limitations"]):
        raise ValueError("Explicit limitations are required")
    if not isinstance(plan["references"], list):
        raise ValueError("references must be a list")
    for ref in plan["references"]:
        if (not isinstance(ref, dict) or set(ref) != {"title", "url", "note"}
                or any(not isinstance(v, str) for v in ref.values())
                or not ref["url"].startswith(("https://", "http://"))):
            raise ValueError("Each reference needs title, http(s) url and provenance note")
    script = (path.parent / plan["experiment"]).resolve()
    if script.suffix != ".py" or not script.is_file():
        raise ValueError(f"Experiment script not found: {script}")
    return plan, script


def fingerprint(plan, script):
    """Reject resume after config, executor or research engine changes."""
    sources = {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    payload = {"plan": plan, "experiment_sha256": digest(script), "engine_sources": sources}
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return key, payload
