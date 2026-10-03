"""Trusted capability contracts and general numeric classification experiments."""
import math
import time

import numpy as np

from .autonomy_domains import method_schema as old_schema, validate_records as old_records, evaluate as old_evaluate
from .project import identity
from .storage import read_json, write_json


CAPABILITIES = {
    "stale_retrieval": {"metric": "literal_update_inclusion", "scope": "Literal update inclusion under a UTF-8 byte context budget; not reader answer accuracy.",
        "needs_training": False, "resources": ["cpu"], "methods": "Fixed lexical relevance, recency and change weighting"},
    "tabular_classification": {"metric": "classification_accuracy", "scope": "Accuracy on numeric, independent labeled examples; no causal, clinical or general deployment claim.",
        "needs_training": True, "resources": ["cpu"], "methods": "Train-only standardization; nearest centroid, k-nearest neighbors, regularized softmax"},
    "fixture_threshold": {"metric": "synthetic_accuracy", "scope": "Synthetic software acceptance only.",
        "needs_training": False, "resources": ["cpu"], "methods": "Synthetic scalar threshold"},
}


def method_schema(domain):
    if domain != "tabular_classification":
        return old_schema(domain)
    return {"type": "object", "properties": {
        "algorithm": {"enum": ["centroid", "knn", "softmax"]},
        "standardize": {"type": "boolean"}, "k": {"type": "integer", "minimum": 1, "maximum": 31},
        "l2": {"type": "number", "minimum": 0, "maximum": 10},
        "epochs": {"type": "integer", "minimum": 10, "maximum": 300}},
        "required": ["algorithm", "standardize", "k", "l2", "epochs"], "additionalProperties": False}


def validate_method(domain, method):
    if domain != "tabular_classification":
        from .autonomy_domains import validate_method as validate
        return validate(domain, method)
    import jsonschema
    jsonschema.validate(method, method_schema(domain))
    if not math.isfinite(method["l2"]):
        raise ValueError("Non-finite regularization")
    # Canonical inactive fields prevent cosmetic duplicate experiments.
    if method["algorithm"] != "knn" and method["k"] != 1:
        raise ValueError("Inactive k must be one")
    if method["algorithm"] != "softmax" and (method["l2"] != 0 or method["epochs"] != 10):
        raise ValueError("Inactive softmax fields must be l2=0 and epochs=10")


def validate_dataset(domain, rows):
    if domain != "tabular_classification":
        return old_records(domain, rows)
    if not isinstance(rows, list) or not 2 <= len(rows) <= 10000:
        raise ValueError("Numeric classification requires 2..10000 rows per split")
    ids, width = set(), None
    for row in rows:
        if set(row) != {"id", "x", "y"} or not isinstance(row["id"], str) or not row["id"] or row["id"] in ids:
            raise ValueError("Classification rows need unique id, numeric x and integer y only")
        x = row["x"]
        if not isinstance(x, list) or not 1 <= len(x) <= 128 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e8 for v in x):
            raise ValueError("Invalid numeric feature vector")
        if width is not None and len(x) != width or type(row["y"]) is not int or not 0 <= row["y"] < 20:
            raise ValueError("Inconsistent features or class label")
        ids.add(row["id"])
        width = len(x)
    return ids


def validate_splits(domain, splits):
    seen_ids, seen_examples, seen_features = set(), set(), set()
    for name, rows in splits.items():
        ids = validate_dataset(domain, rows)
        examples = {identity({k: v for k, v in r.items() if k not in ("id", "uid")}) for r in rows}
        features = {identity(r["x"]) for r in rows} if domain == "tabular_classification" else set()
        if ids & seen_ids or examples & seen_examples or features & seen_features:
            raise ValueError("Data splits overlap, including relabeled duplicate features")
        seen_ids |= ids
        seen_examples |= examples
        seen_features |= features
    if domain == "tabular_classification":
        width = len(splits["training"][0]["x"])
        labels = {r["y"] for r in splits["training"]}
        if len(labels) < 2:
            raise ValueError("Training requires at least two classes")
        for rows in splits.values():
            if any(len(r["x"]) != width or r["y"] not in labels for r in rows):
                raise ValueError("Feature width/class labels incompatible with training")


def evaluate(root, config, method, split, folder, deadline):
    validate_method(config["domain"], method)
    asset_root = root / config["asset_directory"]
    if config["domain"] != "tabular_classification":
        # Existing evaluator reads inputs/<split>.json and preserves its exact metric.
        return old_evaluate(asset_root, config, method, split, folder, deadline)
    train = read_json(asset_root / "inputs/training.json")
    rows = read_json(asset_root / "inputs" / (split + ".json"))
    started = time.monotonic()
    def check():
        if time.time() >= deadline or time.monotonic() - started > config["max_local_seconds"]:
            raise TimeoutError("Classification experiment exceeded its time allowance")
    x = np.asarray([r["x"] for r in train], dtype=float)
    z = np.asarray([r["x"] for r in rows], dtype=float)
    classes, y = np.unique([r["y"] for r in train], return_inverse=True)
    if method["standardize"]:
        mean, scale = x.mean(0), x.std(0)
        scale[scale < 1e-12] = 1
        x, z = (x - mean) / scale, (z - mean) / scale
    # Labels of development/evaluation are only touched after predictions.
    if method["algorithm"] == "centroid":
        centers = np.stack([x[y == c].mean(0) for c in range(len(classes))])
        predictions = classes[((z[:, None, :] - centers) ** 2).sum(2).argmin(1)]
    elif method["algorithm"] == "knn":
        predictions = []
        for row in z:
            check()
            nearest = np.argsort(((x - row) ** 2).sum(1), kind="stable")[:min(method["k"], len(x))]
            predictions.append(classes[np.bincount(y[nearest], minlength=len(classes)).argmax()])
    else:
        x, z = np.c_[x, np.ones(len(x))], np.c_[z, np.ones(len(z))]
        weights = np.zeros((x.shape[1], len(classes)))
        target = np.eye(len(classes))[y]
        lr = 1 / max(1., (x * x).sum() / len(x) + method["l2"])
        for _ in range(method["epochs"]):
            check()
            logits = x @ weights
            probs = np.exp(logits - logits.max(1, keepdims=True))
            probs /= probs.sum(1, keepdims=True)
            penalty = method["l2"] * weights
            penalty[-1] = 0
            weights -= lr * (x.T @ (probs - target) / len(x) + penalty)
        predictions = classes[(z @ weights).argmax(1)]
    check()
    values = {r["id"]: float(int(pred) == r["y"]) for r, pred in zip(rows, predictions)}
    write_json(folder / "predictions.json", [{"id": r["id"], "predicted": int(p)} for r, p in zip(rows, predictions)])
    return {"score": sum(values.values()) / len(values), "n": len(values), "values": values,
            "metric": "classification_accuracy", "split": split, "method": method,
            "wall_seconds": time.monotonic() - started, "fixture_only": config["data_exposure"] == "synthetic_fixture"}
