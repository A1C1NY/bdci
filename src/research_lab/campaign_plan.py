"""Version 2 protocol validation and complete local input fingerprints."""

import hashlib
import json
import math
from pathlib import Path
import re

from .framework import FRAMEWORK_SOURCE, BUDGET_SOURCE
from .storage import digest, read_json


def _ids(values, name, minimum=1, maximum=20):
    if (not isinstance(values, list) or not minimum <= len(values) <= maximum
            or any(not isinstance(x, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", x) for x in values)
            or len(set(values)) != len(values)):
        raise ValueError(f"Invalid {name}: expected distinct safe identifiers")


def load_campaign(path):
    path = Path(path).resolve()
    value = read_json(path)
    required = {"schema_version", "title", "question", "hypothesis", "experiment", "baseline",
                "candidates", "ablations", "development_seeds", "holdout_seeds", "primary_metric",
                "direction", "timeout_seconds", "max_attempts", "budget", "search", "limitations", "sources"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 2:
        raise ValueError(f"Campaign schema 2 requires exactly: {sorted(required)}")
    for field in ("title", "question", "hypothesis", "experiment", "primary_metric"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"{field} must be nonempty")
    _ids([value["baseline"]], "baseline")
    _ids(value["candidates"], "candidates")
    _ids(value["ablations"], "ablations", maximum=8)
    if value["baseline"] in value["candidates"] + value["ablations"]:
        raise ValueError("Baseline cannot also be a candidate or ablation")
    if set(value["candidates"]) & set(value["ablations"]):
        raise ValueError("Candidates and ablations must be disjoint")
    for field in ("development_seeds", "holdout_seeds"):
        seeds = value[field]
        if (not isinstance(seeds, list) or not 2 <= len(seeds) <= 30
                or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds)
                or len(set(seeds)) != len(seeds)):
            raise ValueError(f"Invalid {field}")
    if set(value["development_seeds"]) & set(value["holdout_seeds"]):
        raise ValueError("Development and holdout seeds must be disjoint")
    if value["direction"] not in ("maximize", "minimize"):
        raise ValueError("Invalid direction")
    timeout = value["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError("Invalid timeout_seconds")
    if type(value["max_attempts"]) is not int or not 1 <= value["max_attempts"] <= 3:
        raise ValueError("max_attempts must be 1..3")
    budget = value["budget"]
    if not isinstance(budget, dict) or set(budget) != {"max_attempts", "max_timeout_seconds"}:
        raise ValueError("Invalid campaign budget")
    from .framework import reserve_research_attempt
    reserve_research_attempt({**budget, "reservations": []}, "validation", timeout)
    search = value["search"]
    if not isinstance(search, dict) or set(search) != {"max_trials", "patience", "min_improvement"}:
        raise ValueError("Invalid search configuration")
    for key in ("max_trials", "patience"):
        if type(search[key]) is not int or not 1 <= search[key] <= len(value["candidates"]):
            raise ValueError(f"Invalid search {key}")
    delta = search["min_improvement"]
    if type(delta) not in (int, float) or not math.isfinite(delta) or delta < 0:
        raise ValueError("min_improvement must be finite and nonnegative")
    if (not isinstance(value["limitations"], list) or not value["limitations"]
            or any(not isinstance(x, str) or not x.strip() for x in value["limitations"])):
        raise ValueError("Explicit limitations required")
    script = (path.parent / value["experiment"]).resolve(strict=True)
    if script.suffix != ".py" or not script.is_file():
        raise ValueError("Expected trusted self-contained Python experiment")
    sources = value["sources"]
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    files = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"id", "title", "url", "local_file", "note"}:
            raise ValueError("Source needs id/title/url/local_file/note")
        _ids([source["id"]], "source id")
        if source["id"] in files:
            raise ValueError("Duplicate source ID")
        if any(not isinstance(source[k], str) or not source[k].strip() for k in ("title", "local_file", "note")):
            raise ValueError("Source metadata must be nonempty")
        if not isinstance(source["url"], str) or (source["url"] and not source["url"].startswith(("http://", "https://"))):
            raise ValueError("Source URL must be empty or http(s)")
        source_file = (path.parent / source["local_file"]).resolve(strict=True)
        if not source_file.is_file():
            raise ValueError("Source file missing")
        files[source["id"]] = source_file
    payload = {"protocol": value, "experiment_sha256": digest(script),
               "sources": {key: digest(file) for key, file in files.items()},
               "engine": {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
               "framework": {p.name: digest(p) for p in (FRAMEWORK_SOURCE, BUDGET_SOURCE)}}
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return value, script, files, key, payload


def grid_plan(protocol, methods, seeds):
    return {"schema_version": 1, **{key: protocol[key] for key in
            ("title", "question", "hypothesis", "baseline", "primary_metric", "direction",
             "timeout_seconds", "max_attempts", "limitations")}, "experiment": "../experiment.py",
            "methods": methods, "seeds": seeds, "references": []}
