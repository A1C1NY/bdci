"""Trusted, self-contained CPU experiment. No network, models, or extra packages."""

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import random


def generate(seed, episodes=120):
    rng = random.Random(seed)
    tasks = []
    for _ in range(episodes):
        events, truth = [], {}
        for _ in range(72):
            if rng.random() < 0.65:
                key, value = f"k{rng.randrange(16)}", rng.randrange(10000)
                truth[key] = value
                events.append([key, value])
            else:
                events.append([None, "irrelevant event"])
        query = rng.choice(sorted(truth))
        tasks.append({"events": events, "query": query, "answer": truth[query]})
    return tasks


def predict(events, query, method, capacity=8):
    if method in ("recent_window", "events_only"):
        items = events if method == "recent_window" else [item for item in events if item[0] is not None]
        memory = items[-capacity:]
        predicted = next((value for key, value in reversed(memory) if key == query), None)
    elif method in ("keyed_memory", "fifo_memory", "first_write"):
        retained = OrderedDict()
        for key, value in events:
            if key is None:
                continue
            if method != "first_write" or key not in retained:
                retained[key] = value
            if method in ("keyed_memory", "first_write"):
                retained.move_to_end(key)
            if len(retained) > capacity:
                retained.popitem(last=False)
        predicted = retained.get(query)
        memory = list(retained.items())
    else:
        raise ValueError(f"Unknown registered method: {method}")
    return predicted, len(memory), len(json.dumps(memory, separators=(",", ":")).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tasks = generate(args.seed)
    predictions = []
    for task in tasks:
        prediction, records, size = predict(task["events"], task["query"], args.method)
        predictions.append({"query": task["query"], "expected": task["answer"], "predicted": prediction,
                            "records_retained": records, "serialized_bytes": size})
    correct = sum(item["expected"] == item["predicted"] for item in predictions)
    result = {"method": args.method, "seed": args.seed,
              "metrics": {"accuracy": correct / len(tasks), "correct": correct, "total": len(tasks),
                          "mean_records": sum(x["records_retained"] for x in predictions) / len(tasks),
                          "mean_serialized_bytes": sum(x["serialized_bytes"] for x in predictions) / len(tasks)},
              "provenance": {"dataset": "synthetic-key-recall-v2", "episodes": len(tasks),
                             "dataset_sha256": hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest(),
                             "capacity_records": 8, "llm_calls": 0, "llm_tokens": 0},
              "predictions": predictions}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"{args.method} seed={args.seed} accuracy={correct}/{len(tasks)}")


if __name__ == "__main__":
    main()
