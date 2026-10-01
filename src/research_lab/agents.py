"""Offline roles with a small planner contract; no model simulation or API calls."""

from typing import Protocol


class Planner(Protocol):
    def propose(self, candidates: list[str], history: list[dict], *,
                max_trials: int, patience: int) -> str | None: ...


class LocalPlanner:
    """Ordered, preregistered candidates; only development history is accepted."""

    def propose(self, candidates, history, *, max_trials, patience):
        if len(history) >= max_trials:
            return None
        if len(history) >= patience and not any(item["accepted"] for item in history[-patience:]):
            return None
        tried = {item["candidate"] for item in history}
        return next((candidate for candidate in candidates if candidate not in tried), None)


def assess_candidate(candidate, summary, incumbent, incumbent_score, min_improvement):
    scores = {item["method"]: item["mean"] for item in summary["methods"]}
    if incumbent_score is None:
        incumbent_score = scores[summary["baseline"]]
    sign = 1 if summary["direction"] == "maximize" else -1
    improvement = sign * (scores[candidate] - incumbent_score)
    accepted = improvement > min_improvement
    return {"candidate": candidate, "score": scores[candidate],
            "previous_incumbent": incumbent, "previous_score": incumbent_score,
            "improvement": improvement, "accepted": accepted,
            "decision": "retain" if accepted else "reject",
            "reason": "Development improvement exceeds the registered threshold" if accepted
                      else "Development improvement does not exceed the registered threshold"}
