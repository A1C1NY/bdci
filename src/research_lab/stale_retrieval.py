"""Trusted, label-blind retrieval DSL for a bounded-context STALE audit."""
from collections import Counter
import math
import re
import unicodedata

STOP = set("a an the i me my you your we our and or of to for in on at is are was were be been being it this that with as from by do does did can could would should have has had if so how what when where which please user still based history conversation".split())
CHANGE = re.compile(r"\b(now|anymore|no longer|instead|since|recently|changed|switched|started|stopped|quit|moved|new|but|however|actually)\b", re.I)


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def validate_policy(policy):
    if set(policy) != {"name", "relevance", "recency", "change"}:
        raise ValueError("Unknown policy fields; executable code is not supported")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", policy["name"]):
        raise ValueError("Invalid policy name")
    for key in ("relevance", "recency", "change"):
        if type(policy[key]) not in (int, float) or not math.isfinite(policy[key]) or not 0 <= policy[key] <= 1:
            raise ValueError("Weights must be finite numbers in [0,1]")
    if not any(policy[k] for k in ("relevance", "recency", "change")):
        raise ValueError("Empty scoring policy")
    return policy


def public_view(record):
    # Explicit allowlist: labels/annotation/session indices never reach selector.
    return {"uid":record["uid"], "sessions":record["haystack_session"],
            "timestamps":record["timestamps"], "queries":record["probing_queries"]}


class Retriever:
    def __init__(self, view):
        self.docs = []
        for si, session in enumerate(view["sessions"]):
            for ti, turn in enumerate(session):
                if turn["role"] == "user":
                    text = turn["content"]
                    self.docs.append({"session":si, "turn":ti, "text":text,
                        "serialized": f"[session {si}, turn {ti}] {text}\n"})
        self.counts = [Counter(tokens(d["text"])) for d in self.docs]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg = sum(self.lengths) / max(1,len(self.lengths))
        self.df = Counter(t for c in self.counts for t in c)

    def select(self, query, policy, byte_budget):
        validate_policy(policy)
        scores = []
        for c, length in zip(self.counts, self.lengths):
            score = 0.0
            for t in set(tokens(query)):
                tf = c[t]
                if tf:
                    idf = math.log(1+(len(self.docs)-self.df[t]+.5)/(self.df[t]+.5))
                    score += idf * tf * 2.2 / (tf+1.2*(.25+.75*length/max(1,self.avg)))
            scores.append(score)
        maximum = max(scores, default=1) or 1
        ranking = sorted(range(len(self.docs)), key=lambda i: (
            policy["relevance"]*scores[i]/maximum + policy["recency"]*i/max(1,len(self.docs)-1)
            + policy["change"]*bool(CHANGE.search(self.docs[i]["text"])), i), reverse=True)
        selected, used = [], 0
        for i in ranking:
            size = len(self.docs[i]["serialized"].encode("utf-8"))
            if used+size <= byte_budget:
                selected.append(i)
                used += size
        selected.sort()
        text = "".join(self.docs[i]["serialized"] for i in selected)
        return {"context":text, "bytes":used,
                "sessions":sorted({self.docs[i]["session"] for i in selected})}


BASELINES = [{"name":"bm25", "relevance":1,"recency":0,"change":0},
             {"name":"recent", "relevance":0,"recency":1,"change":0},
             {"name":"bm25_recent", "relevance":1,"recency":.25,"change":0}]


def evaluate(records, policies, budgets=(4096,8192)):
    rows=[]
    for r in records:
        retriever=Retriever(public_view(r))
        for dim, query in r["probing_queries"].items():
            for policy in policies:
                for budget in budgets:
                    selected=retriever.select(query, policy, budget)
                    text=normalize(selected["context"])
                    rows.append({"uid":r["uid"],"type":r["type"],"query":dim,
                        "policy":policy["name"],"budget":budget,"bytes":selected["bytes"],
                        "old_present":normalize(r["M_old"]) in text,
                        "new_present":normalize(r["M_new"]) in text,
                        "new_session_present":r["relevant_session_index"][-1] in selected["sessions"]})
    return rows
