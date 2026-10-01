"""Real CPU-only synthetic benchmark; independent of research_lab and any LLM."""

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import random


def generate(seed, episodes=80):
    rng = random.Random(seed)
    tasks = []
    for _ in range(episodes):
        events = []
        truth = {}
        for _ in range(60):
            if rng.random() < 0.55:
                key, value = f"k{rng.randrange(12)}", rng.randrange(10000)
                events.append([key, value])
                truth[key] = value
            else:
                events.append([None, "irrelevant event"])
        query = rng.choice(sorted(truth))
        tasks.append({"events": events, "query": query, "answer": truth[query]})
    return tasks


def predict(task, method, capacity=8):
    if method == "recent_window":
        retained = task["events"][-capacity:]
        answer = next((value for key, value in reversed(retained) if key == task["query"]), None)
        return answer, len(retained)
    if method == "keyed_memory":
        memory = OrderedDict()
        for key, value in task["events"]:
            if key is None:
                continue
            memory[key] = value
            memory.move_to_end(key)
            if len(memory) > capacity:
                memory.popitem(last=False)
        return memory.get(task["query"]), len(memory)
    raise ValueError(method)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["recent_window", "keyed_memory"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tasks = generate(args.seed)
    predictions = []
    for task in tasks:
        prediction, records = predict(task, args.method)
        predictions.append({"query": task["query"], "expected": task["answer"],
                            "predicted": prediction, "records_retained": records})
    correct = sum(x["expected"] == x["predicted"] for x in predictions)
    result = {"method": args.method, "seed": args.seed,
              "metrics": {"accuracy": correct / len(tasks), "correct": correct,
                          "total": len(tasks), "mean_records": sum(x["records_retained"] for x in predictions) / len(tasks)},
              "provenance": {"dataset": "synthetic-key-recall-v1", "episodes": len(tasks),
                             "events_per_episode": 60, "capacity_records": 8,
                             "dataset_sha256": hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest(),
                             "llm_calls": 0, "llm_tokens": 0},
              "predictions": predictions}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"{args.method} seed={args.seed} accuracy={correct}/{len(tasks)}")


if __name__ == "__main__":
    main()
