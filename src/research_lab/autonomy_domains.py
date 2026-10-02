"""Trusted experiment families for bounded autonomous research, never generated Python."""
import math
import time

import numpy as np

from .stale_retrieval import Retriever, normalize, public_view, validate_policy
from .storage import read_json, write_json


def method_schema(domain):
    if domain == "fixture_threshold":
        return {"type": "object", "properties": {"threshold": {"type": "number", "minimum": 0, "maximum": 1}},
                "required": ["threshold"], "additionalProperties": False}
    return {"type": "object", "properties": {k: {"type": "number", "minimum": 0, "maximum": 1}
                                               for k in ("relevance", "recency", "change")},
            "required": ["relevance", "recency", "change"], "additionalProperties": False}


def validate_method(domain, method):
    import jsonschema
    jsonschema.validate(method, method_schema(domain))
    if not all(type(v) in (int, float) and math.isfinite(v) for v in method.values()):
        raise ValueError("Non-finite method parameter")
    if domain == "stale_retrieval":
        validate_policy({"name": "candidate", **method})


def validate_records(domain, rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Dataset must contain records")
    ids = []
    for row in rows:
        uid = row["id" if domain == "fixture_threshold" else "uid"]
        if not isinstance(uid, str) or not uid.strip():
            raise ValueError("Dataset identifiers must be nonempty strings")
        ids.append(uid)
        if domain == "fixture_threshold":
            if type(row["x"]) not in (int, float) or not math.isfinite(row["x"]) or row["y"] not in (0, 1):
                raise ValueError("Invalid threshold fixture")
        else:
            if not row["M_new"].strip() or not row["M_old"].strip() or not row["probing_queries"]:
                raise ValueError("Missing STALE annotations/queries")
            if any(not isinstance(q, str) or not q.strip() for q in row["probing_queries"].values()):
                raise ValueError("Invalid STALE query")
            public_view(row)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate dataset identifiers")
    return set(ids)


def evaluate(root, config, method, split, output, deadline):
    """Only aggregates are subsequently passed to workers; labels stay in this evaluator."""
    validate_method(config["domain"], method)
    rows = read_json(root / "inputs" / (split + ".json"))
    values, details = {}, []
    started = time.monotonic()
    for i, record in enumerate(rows):
        if time.time() >= deadline or time.monotonic() - started > config["max_local_seconds"]:
            raise TimeoutError("Local experiment time limit exceeded")
        if config["domain"] == "fixture_threshold":
            values[record["id"]] = float((record["x"] >= method["threshold"]) == bool(record["y"]))
        else:
            retriever = Retriever(public_view(record))
            found = []
            for dimension, query in record["probing_queries"].items():
                selected = retriever.select(query, {"name": "candidate", **method}, config["context_bytes"])
                success = int(normalize(record["M_new"]) in normalize(selected["context"]))
                found.append(success)
                details.append({"uid": record["uid"], "dimension": dimension, **selected,
                                "literal_update": success})
            values[record["uid"]] = sum(found) / len(found)
        if (i + 1) % 10 == 0:
            write_json(root / "progress.json", {"split": split, "completed": i + 1, "total": len(rows)})
    # Contexts are separate immutable evidence, never used as instructions or planning feedback.
    write_json(output / "contexts.json", details)
    return {"score": sum(values.values()) / len(values), "n": len(values), "values": values,
            "metric": "synthetic_accuracy" if config["domain"] == "fixture_threshold" else "literal_update_inclusion",
            "split": split, "method": method, "wall_seconds": time.monotonic() - started,
            "fixture_only": config["domain"] == "fixture_threshold"}


def paired(baseline, candidate):
    if set(baseline["values"]) != set(candidate["values"]) or baseline["metric"] != candidate["metric"]:
        raise ValueError("Unmatched evaluation results")
    differences = np.array([candidate["values"][k] - baseline["values"][k] for k in sorted(baseline["values"])])
    rng = np.random.default_rng(20261003)
    # Bounded memory even for larger datasets; aggregate by scenario, never by query.
    boot = [float(rng.choice(differences, len(differences), replace=True).mean()) for _ in range(10000)]
    return {"baseline": baseline["score"], "candidate": candidate["score"],
            "gain": float(differences.mean()), "ci95": np.quantile(boot, [.025, .975]).tolist(),
            "n": len(differences), "metric": baseline["metric"], "resamples": 10000, "seed": 20261003}
