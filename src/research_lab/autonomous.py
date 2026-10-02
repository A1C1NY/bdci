"""Durable autonomous research inside an explicitly authorized experiment family.

Machine reviews never impersonate human approval. Scientific success is separate
from execution completion. No model output can execute code or change evaluation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import time
import platform
from importlib.metadata import version

import jsonschema

from .autonomy_domains import evaluate, method_schema, paired, validate_method, validate_records
from .autonomy_worker import FixtureWorker, NativeWorker
from .project import contained, identity
from .storage import digest, event, read_json, run_lock, utc_now, write_json

TEXT = {"type": "string", "minLength": 10, "maxLength": 2000}


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


REVIEW = object_schema({"verdict": {"enum": ["approve", "revise", "stop"]}, "reason": TEXT,
                       "issues": {"type": "array", "items": TEXT, "maxItems": 12},
                       "binding": {"type": "string", "pattern": "^[a-f0-9]{64}$"}})
NEXT = object_schema({"action": {"enum": ["continue", "stop"]}, "reason": TEXT})
DRAFT = object_schema({**{key: TEXT for key in ("title", "abstract", "introduction", "discussion", "limitations")},
                       "citations": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}}})
TERMINAL = {"completed", "stopped", "budget_exhausted", "deadline_exceeded", "needs_attention"}


def implementation():
    directory = Path(__file__).parent
    pins = {name: digest(directory / name) for name in (
        "autonomous.py", "autonomy_domains.py", "autonomy_worker.py", "autonomy_export.py",
        "stale_retrieval.py", "native_research.py", "storage.py", "model_client.py", "model_config.py",
        "token_ledger.py", "project.py", "report.py", "framework.py")}
    root = directory.parents[1]
    for name in ("requirements.lock", "integrations/jiuwenswarm/workflow_v4.py", "integrations/jiuwenswarm/upstream_v4.json"):
        pins[name] = digest(root / name)
    pins["runtime"] = {"python": platform.python_version(), "numpy": version("numpy"), "jsonschema": version("jsonschema")}
    return pins


def validate_config(config):
    if config.get("version") != 1 or config.get("domain") not in ("stale_retrieval", "fixture_threshold"):
        raise ValueError("Unsupported autonomous research contract")
    if not isinstance(config.get("question"), str) or len(config["question"].strip()) < 10:
        raise ValueError("A bounded research question is required")
    for key, maximum in {"max_candidates": 20, "patience": 20, "max_review_revisions": 5,
                         "max_model_calls": 200, "max_wall_seconds": 604800,
                         "max_local_seconds": 86400, "context_bytes": 65536}.items():
        if type(config.get(key)) is not int or not 1 <= config[key] <= maximum:
            raise ValueError("Invalid autonomous bound: " + key)
    gain = config.get("min_gain")
    if type(gain) not in (int, float) or not 0 <= gain <= 1:
        raise ValueError("Invalid minimum gain")
    if config.get("data_exposure") not in ("reused", "unseen_to_this_workflow", "synthetic_fixture"):
        raise ValueError("Declare prior data exposure")
    if config["domain"] == "fixture_threshold" and config["data_exposure"] != "synthetic_fixture":
        raise ValueError("Fixture domain must be labeled synthetic")
    if config["domain"] != "fixture_threshold" and config["data_exposure"] == "synthetic_fixture":
        raise ValueError("Real data cannot use fixture provenance")
    roles = config.get("roles", {})
    if (set(roles) != {"director", "writer", "reviewers"} or not isinstance(roles["reviewers"], list)
            or len(roles["reviewers"]) != 2 or len(set(roles["reviewers"])) != 2):
        raise ValueError("Two distinct reviewer aliases are required")
    aliases = {roles["director"], roles["writer"], *roles["reviewers"]}
    if set(config.get("model_budget", {})) != aliases or any(type(v) is not int or v < 0 for v in config["model_budget"].values()):
        raise ValueError("Explicit per-alias campaign budgets required")
    if config["domain"] != "fixture_threshold" and not all(config["model_budget"].values()):
        raise ValueError("Real workers require a nonzero authorized budget")
    validate_method(config["domain"], config["baseline"])
    if type(config.get("compile_pdf", False)) is not bool:
        raise ValueError("compile_pdf must be boolean")
    if not config.get("sources"):
        raise ValueError("Approved full-text sources required")


def initialize(config_path, project):
    path = Path(config_path).resolve()
    config = read_json(path)
    validate_config(config)
    root = Path(project).resolve()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", root.name):
        raise ValueError("Use a unique project identifier")
    if root.exists():
        raise ValueError("Project exists; resume it or choose a new ID")
    datasets, ids, bodies = {}, {}, {}
    for split in ("development", "evaluation"):
        data = read_json((path.parent / config[split]).resolve())
        ids[split] = validate_records(config["domain"], data)
        bodies[split] = {identity({k: v for k, v in row.items() if k not in ("uid", "id")}) for row in data}
        datasets[split] = data
    if ids["development"] & ids["evaluation"] or bodies["development"] & bodies["evaluation"]:
        raise ValueError("Development and evaluation data overlap")
    sources, source_ids = [], set()
    for item in config["sources"]:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", item["id"]) or item["id"] in source_ids:
            raise ValueError("Unique safe source identifiers required")
        source_ids.add(item["id"])
        text = (path.parent / item["path"]).resolve().read_text("utf-8-sig")
        if not 20 <= len(text.encode()) <= 60000 or not item["title"].strip():
            raise ValueError("Source snapshot empty or exceeds 60KB; provide a bounded full-text extract")
        if not item["url"].startswith(("https://", "http://")):
            raise ValueError("Source attribution URL required")
        sources.append({"id": item["id"], "title": item["title"], "url": item["url"], "text": text,
                        "verification": "supplied source snapshot; excerpt checks do not prove entailment"})
    if sum(len(s["text"].encode()) for s in sources) > 70000:
        raise ValueError("Source bundle exceeds worker input allowance")
    root.mkdir(parents=True)
    for split, data in datasets.items():
        write_json(root / "inputs" / (split + ".json"), data)
    write_json(root / "inputs/sources.json", sources)
    write_json(root / "inputs/config.json", config)
    pins = {p.relative_to(root).as_posix(): digest(p) for p in (root / "inputs").glob("*.json")}
    state = {"schema_version": 7, "id": root.name, "question": config["question"], "status": "ready",
             "phase": "baseline", "created_at": utc_now(), "deadline": time.time() + config["max_wall_seconds"],
             "input_hashes": pins, "implementation": implementation(), "worker_identity": None,
             "operations": {}, "reviews": [], "trials": [], "attempt": 0, "stagnant": 0,
             "draft_revision": 0, "best_method": config["baseline"], "best_score": None,
             "evaluation_exposed": False, "model_calls": 0, "worker_calls": 0,
             "fixture_only": config["domain"] == "fixture_threshold",
             "charged_or_reserved": {a: 0 for a in config["model_budget"]}, "decisions": [],
             "scientific_success_not_implied": True, "external_submission": False}
    write_json(root / "autonomy-state.json", state)
    return state


class Research:
    def __init__(self, root, worker):
        self.root = Path(root).resolve()
        self.worker = worker
        self.path = self.root / "autonomy-state.json"

    def save(self):
        self.state["updated_at"] = utc_now()
        write_json(self.path, self.state)

    def verify(self):
        if implementation() != self.state["implementation"]:
            raise ValueError("Frozen implementation changed; use the recorded checkout")
        for name, sha in self.state["input_hashes"].items():
            if digest(contained(self.root, name)) != sha:
                raise ValueError("Frozen input changed: " + name)
        for op in self.state["operations"].values():
            if op["status"] == "completed":
                for name, sha in op["files"].items():
                    if digest(contained(self.root, name)) != sha:
                        raise ValueError("Autonomous evidence changed: " + name)

    def memo(self, name, payload, action, *, alias=None):
        """Durable intent + committed receipt. Unknown paid/holdout attempts are not retried."""
        signature = identity(payload)
        previous = self.state["operations"].get(name)
        folder = self.root / "evidence" / name
        if previous:
            if previous["signature"] != signature:
                raise ValueError("Operation input changed: " + name)
            receipt = folder / "receipt.json"
            if previous["status"] == "completed":
                return read_json(folder / "result.json")
            if receipt.exists():
                committed = read_json(receipt)
                if committed["signature"] != signature:
                    raise ValueError("Receipt signature differs")
                for n, sha in committed["files"].items():
                    if digest(contained(self.root, n)) != sha:
                        raise ValueError("Incomplete receipt")
                previous.update(committed, status="completed")
                self.save()
                return read_json(folder / "result.json")
            raise RuntimeError("Uncertain prior operation retained; no automatic duplicate: " + name)
        if time.time() >= self.state["deadline"]:
            raise TimeoutError("Campaign deadline exceeded")
        reservation = self.worker.reservation(alias) if alias else 0
        if alias:
            if self.state["deadline"] - time.time() < getattr(self.worker, "timeout_allowance", lambda _: 0)(alias):
                raise TimeoutError("Insufficient campaign time for a bounded model request")
            try:
                self.worker.ready(alias)  # No paid intent exists on connectivity failure.
            except OSError as exc:
                raise GatewayUnavailable(type(exc).__name__) from exc
            if (self.state["worker_calls"] >= self.config["max_model_calls"] or
                    self.state["charged_or_reserved"][alias] + reservation > self.config["model_budget"][alias]):
                raise BudgetLimit("Autonomous model budget exhausted")
            self.state["worker_calls"] += 1
            self.state["model_calls"] += int(not self.worker.fixture)
            self.state["charged_or_reserved"][alias] += reservation
        op = {"status": "running", "signature": signature, "alias": alias,
              "reservation": reservation, "started_at": utc_now()}
        if alias and not self.worker.fixture:
            op["native_stage"] = "autonomous-" + identity(str(self.root))[:16] + "-" + name
        self.state["operations"][name] = op
        self.save()
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "request.json", payload)
        try:
            result, charge = action(folder, reservation)
            if alias and (type(charge) is not int or charge < 0):
                raise ValueError("Invalid worker accounting")
            if alias and charge > reservation:
                self.state["charged_or_reserved"][alias] += charge - reservation
                op["charged_or_reserved"] = charge
                raise BudgetLimit("Worker exceeded declared reservation; actual charge retained")
            write_json(folder / "result.json", result)
            files = {p.relative_to(self.root).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()}
            committed = {"signature": signature, "files": files, "charged_or_reserved": charge,
                         "finished_at": utc_now()}
            write_json(folder / "receipt.json", committed)
            op.update(committed, status="completed")
            if alias:
                # Conservative reservations survive crashes; completed normal calls settle exactly once.
                self.state["charged_or_reserved"][alias] -= reservation - charge
            self.save()
            event(self.root / "events.jsonl", "operation_completed", job=name, status="completed")
            return result
        except BaseException as exc:
            op.update(status="failed", error=type(exc).__name__)
            self.save()
            raise

    def ask(self, name, alias, payload, schema):
        payload = {**payload, "output_contract": schema}
        upper_bytes = len(json.dumps(payload, ensure_ascii=False).encode()) + 2 * len(json.dumps(schema).encode()) + 2048
        if upper_bytes > getattr(self.worker, "input_limit", lambda _: 1_000_000)(alias):
            raise ValueError("Bounded worker context exceeds route allowance; no request admitted")
        def call(folder, reservation):
            stage = "autonomous-" + identity(str(self.root))[:16] + "-" + name
            result, charge = self.worker.generate(alias, stage, payload, schema, reservation)
            jsonschema.validate(result, schema)
            return result, charge
        return self.memo(name, payload, call, alias=alias)

    def review(self, name, evidence):
        binding = identity(evidence)
        results = []
        for index, alias in enumerate(self.config["roles"]["reviewers"]):
            result = self.ask(name + "-critic-" + str(index), alias,
                {"role": "review", "binding": binding, "evidence": evidence,
                 "rubric": "Independently inspect falsifiability, relevance of source excerpts, leakage, matched controls, "
                 "metric scope, missingness and unsupported novelty/causal claims. Approve only with no unresolved issues. "
                 "Revise if a bounded correction is possible; stop if the direction is unsupported. Return the exact binding. "
                 "Machine consensus is not human validation or a venue score."}, REVIEW)
            if result["binding"] != binding or (result["verdict"] == "approve" and result["issues"]):
                raise ValueError("Review does not bind to evidence or has unresolved issues")
            results.append({"alias": alias, **result})
        record = {"id": name, "binding": binding, "actor_type": "model_review_panel", "reviews": results}
        if not any(r["id"] == name for r in self.state["reviews"]):
            self.state["reviews"].append(record)
        self.save()
        if any(r["verdict"] == "stop" for r in results):
            return "stop"
        return "approve" if all(r["verdict"] == "approve" for r in results) else "revise"

    def experiment(self, name, method, split):
        return self.memo(name, {"method": method, "split": split, "dataset": self.state["input_hashes"]["inputs/" + split + ".json"]},
                         lambda folder, _: (evaluate(self.root, self.config, method, split, folder, self.state["deadline"]), 0))

    def public_result(self, result):
        return {k: v for k, v in result.items() if k != "values"}

    def proposal(self):
        schema = object_schema({"title": TEXT, "hypothesis": TEXT, "falsifier": TEXT,
            "method": method_schema(self.config["domain"]), "limitations": TEXT,
            "sources": {"type": "array", "minItems": 1, "maxItems": len(self.sources),
                        "items": object_schema({"id": {"type": "string"}, "excerpt": {"type": "string", "minLength": 20, "maxLength": 600}, "relevance": TEXT})}})
        return self.ask("proposal-" + str(self.state["attempt"]), self.config["roles"]["director"],
            {"role": "propose", "question": self.config["question"], "domain": self.config["domain"],
             "attempt": self.state["attempt"], "sources": self.sources, "history": self.state["trials"],
             "feedback": self.state.get("feedback", []), "baseline": self.config["baseline"],
             "best": self.state["best_method"], "metric_scope": "Literal inclusion only for STALE, not answer correctness.",
             "constraints": "Choose one new bounded method. Do not invent references, execute code or alter the evaluator. "
             "Explain a falsifiable hypothesis and cite exact supplied source excerpts. Prior work may already contain your idea. "
             "No raw development labels or evaluation results are available during search."}, schema)

    def reject(self, reason):
        # Full criticism remains in immutable review operations; planning gets a bounded summary.
        self.state["trials"].append({"attempt": self.state["attempt"], "status": "rejected", "reason": reason[:1000]})
        self.state["feedback"] = [reason[:1000]]
        self.state["attempt"] += 1
        self.state["stagnant"] += 1
        self.state["phase"] = "propose"

    def transition(self):
        s, c = self.state, self.config
        phase = s["phase"]
        if phase == "baseline":
            result = self.experiment("baseline-development", c["baseline"], "development")
            s.update(best_score=result["score"], phase="propose")
        elif phase == "propose":
            if s["attempt"] >= c["max_candidates"] or s["stagnant"] >= c["patience"]:
                s["phase"] = "freeze"
                return
            proposal = self.proposal()
            try:
                validate_method(c["domain"], proposal["method"])
                fingerprint = identity(proposal["method"])
                if fingerprint == identity(c["baseline"]) or any(t.get("fingerprint") == fingerprint for t in s["trials"]):
                    raise ValueError("Duplicate method")
                registry = {x["id"]: x for x in self.sources}
                for card in proposal["sources"]:
                    if card["id"] not in registry or card["excerpt"] not in registry[card["id"]]["text"]:
                        raise ValueError("Fabricated or unverified source excerpt")
            except ValueError as exc:
                self.reject(str(exc))
                return
            s.update(proposal=proposal, phase="design_review")
        elif phase == "design_review":
            verdict = self.review("design-" + str(s["attempt"]), {"proposal": s["proposal"], "sources": self.sources,
                "question": c["question"], "data_exposure": c["data_exposure"], "context_bytes": c["context_bytes"],
                "baseline": c["baseline"], "search_history": s["trials"]})
            if verdict == "approve":
                s["phase"] = "development"
            elif verdict == "stop":
                s.update(status="stopped", stop_reason="Design review rejected research direction")
            else:
                self.reject("Design review requested revision: " + json.dumps(s["reviews"][-1]["reviews"]))
        elif phase == "development":
            result = self.experiment("candidate-" + str(s["attempt"]), s["proposal"]["method"], "development")
            improved = result["score"] > s["best_score"] + c["min_gain"]
            s["trials"].append({"attempt": s["attempt"], "fingerprint": identity(s["proposal"]["method"]),
                "method": s["proposal"]["method"], "hypothesis": s["proposal"]["hypothesis"][:600],
                "result": self.public_result(result), "status": "evaluated", "improved": improved})
            if improved:
                s.update(best_method=s["proposal"]["method"], best_score=result["score"], stagnant=0)
            else:
                s["stagnant"] += 1
            s["attempt"] += 1
            s["phase"] = "next"
        elif phase == "next":
            if s["attempt"] >= c["max_candidates"] or s["stagnant"] >= c["patience"]:
                s["phase"] = "freeze"
                return
            decision = self.ask("next-" + str(s["attempt"]), c["roles"]["director"],
                {"role": "next", "development_history": s["trials"], "remaining_candidates": c["max_candidates"] - s["attempt"],
                 "task": "Stop if there is no supported next experiment; otherwise continue within the fixed family. No evaluation data may inform this decision."}, NEXT)
            s["decisions"].append(decision)
            s["phase"] = "propose" if decision["action"] == "continue" else "freeze"
        elif phase == "freeze":
            if not any(t["status"] == "evaluated" for t in s["trials"]):
                s.update(status="stopped", stop_reason="No candidate passed design review")
                return
            protocol = {"question": c["question"], "selected": s["best_method"], "baseline": c["baseline"],
                "development_history": s["trials"], "data_exposure": c["data_exposure"],
                "evaluation_dataset_sha256": s["input_hashes"]["inputs/evaluation.json"], "min_gain": c["min_gain"],
                "primary": "Selected minus baseline mean scenario score; 10000 paired bootstrap samples, seed 20261003",
                "selection_rule": "Strict development improvement > min_gain; ties keep incumbent; single frozen evaluation",
                "context_bytes": c["context_bytes"], "implementation": s["implementation"]}
            verdict = self.review("freeze-" + str(s["attempt"]), protocol)
            if verdict == "approve":
                s["frozen"] = self.memo("frozen-protocol", protocol, lambda folder, _: (protocol, 0))
                s["phase"] = "evaluation"
            else:
                s.update(status="stopped", stop_reason="Protocol freeze did not pass independent machine review")
        elif phase == "evaluation":
            s["evaluation_exposed"] = True
            self.save()  # Durable barrier: no path returns to planning after this point.
            baseline = self.experiment("baseline-evaluation", s["frozen"]["baseline"], "evaluation")
            candidate = self.experiment("selected-evaluation", s["frozen"]["selected"], "evaluation")
            s["analysis"] = self.memo("analysis", {"baseline": baseline, "candidate": candidate},
                lambda folder, _: (paired(baseline, candidate), 0))
            s["phase"] = "interpretation"
        elif phase == "interpretation":
            verdict = self.review("interpretation", {"protocol": s["frozen"], "analysis": s["analysis"],
                "limitations": "Reused data must be disclosed. Literal inclusion is not answer accuracy. No novelty or venue score is established. Negative/inconclusive outcomes are valid."})
            s["interpretation_verdict"] = verdict
            if verdict == "approve":
                s["phase"] = "write"
            else:
                s.update(status="stopped", stop_reason="Interpretation not accepted; evidence retained without a paper claim")
        elif phase == "write":
            s["draft"] = self.ask("draft-" + str(s["draft_revision"]), c["roles"]["writer"],
                {"role": "write", "protocol": s["frozen"], "analysis": s["analysis"], "sources": self.sources,
                 "feedback": s.get("writing_feedback", []),
                 "task": "Write concise English research prose. Cite only supplied source IDs. Clearly disclose data exposure and fixture status. "
                 "No publication/novelty/answer-quality claims. Numerical methods/results are supplied deterministically by the exporter. "
                 "Do not reinterpret a negative or uncertain result as success. Do not write numerical quantities or years "
                 "in prose; use {{primary_result}} if you need the computed quantitative result."}, DRAFT)
            prose = " ".join(s["draft"][k] for k in ("title", "abstract", "introduction", "discussion", "limitations"))
            if (not set(s["draft"]["citations"]) <= {x["id"] for x in self.sources}
                    or re.search(r"\d", prose) or "{{" in prose.replace("{{primary_result}}", "")):
                s["writing_feedback"] = ["Use supplied citation IDs, no numerical claims/years in prose, and only {{primary_result}} as a result placeholder."]
                self.rewrite_or_stop()
            else:
                s["phase"] = "paper_review"
        elif phase == "paper_review":
            verdict = self.review("paper-" + str(s["draft_revision"]), {"draft": s["draft"], "sources": self.sources,
                "analysis": s["analysis"], "protocol": s["frozen"], "task": "Check every prose claim against evidence and full source snapshots. Do not approve unsupported gains or invented novelty."})
            if verdict == "approve":
                s["phase"] = "export"
            elif verdict == "revise":
                s["writing_feedback"] = [{"alias": r["alias"], "reason": r["reason"][:1000],
                    "issues": [issue[:400] for issue in r["issues"][:6]]} for r in s["reviews"][-1]["reviews"]]
                self.rewrite_or_stop()
            else:
                s.update(status="stopped", stop_reason="Machine paper review rejected manuscript")
        elif phase == "export":
            from .autonomy_export import export
            s["deliverables"] = self.memo("deliverables", {"analysis": s["analysis"], "draft": s["draft"], "protocol": s["frozen"]},
                lambda folder, _: (export(folder, self.config, s, self.sources), 0))
            s.update(status="completed", phase="done")
        else:
            raise ValueError("Unknown autonomous phase")

    def rewrite_or_stop(self):
        self.state["draft_revision"] += 1
        if self.state["draft_revision"] > self.config["max_review_revisions"]:
            self.state.update(status="stopped", stop_reason="Manuscript revision limit exhausted")
        else:
            self.state["phase"] = "write"

    def run(self, *, max_steps=None):
        with run_lock(self.root):
            self.state = read_json(self.path)
            self.verify()
            self.config = read_json(self.root / "inputs/config.json")
            self.sources = read_json(self.root / "inputs/sources.json")
            if self.worker.fixture != (self.config["domain"] == "fixture_threshold"):
                raise ValueError("Fixture workers are prohibited for real research")
            if self.state["worker_identity"] is not None and self.state["worker_identity"] != self.worker.identity:
                raise ValueError("Worker routes/ledger changed; preserve the existing run")
            self.state["worker_identity"] = self.worker.identity
            if not self.worker.fixture:
                aliases = self.config["roles"]["reviewers"]
                routes = self.worker.identity["routes"]
                if (routes[aliases[0]]["base_url"], routes[aliases[0]]["model"]) == (routes[aliases[1]]["base_url"], routes[aliases[1]]["model"]):
                    raise ValueError("Review aliases must route to distinct models")
            if self.state["status"] in TERMINAL:
                return self.state
            self.state.update(status="running", last_error=None)
            self.save()
            steps = 0
            try:
                while self.state["status"] == "running" and (max_steps is None or steps < max_steps):
                    if time.time() >= self.state["deadline"]:
                        raise TimeoutError("Campaign deadline exceeded")
                    if self.state["evaluation_exposed"] and self.state["phase"] in {"propose", "development", "next", "freeze", "design_review"}:
                        raise ValueError("Evaluation feedback cannot return to search")
                    self.transition()
                    steps += 1
                    self.save()
                    event(self.root / "events.jsonl", "autonomous_transition", status=self.state["status"], decision=self.state["phase"])
                if self.state["status"] == "running":
                    self.state["status"] = "ready"
            except BudgetLimit as exc:
                self.state.update(status="budget_exhausted", last_error=str(exc))
            except GatewayUnavailable as exc:
                self.state.update(status="waiting_for_gateway", last_error=str(exc))
            except TimeoutError as exc:
                self.state.update(status="deadline_exceeded", last_error=str(exc))
            except Exception as exc:
                self.state.update(status="needs_attention", last_error=type(exc).__name__ + ": " + str(exc))
            self.save()
            return self.state


class BudgetLimit(RuntimeError):
    pass


class GatewayUnavailable(RuntimeError):
    pass


def status(project):
    state = read_json(Path(project) / "autonomy-state.json")
    keys = ("id", "question", "status", "phase", "attempt", "best_score", "evaluation_exposed",
            "charged_or_reserved", "model_calls", "worker_calls", "fixture_only", "last_error", "stop_reason", "scientific_success_not_implied", "updated_at")
    return {k: state[k] for k in keys if k in state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("project")
    init.add_argument("--config", required=True)
    run = commands.add_parser("run")
    run.add_argument("project")
    run.add_argument("--allow-models", action="store_true")
    run.add_argument("--fixture", action="store_true")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--wait-seconds", type=int, default=0, help="Bounded wait for gateway recovery; no requests before connectivity")
    commands.add_parser("status").add_argument("project")
    args = parser.parse_args(argv)
    if args.command == "init":
        initialize(args.config, args.project)
    elif args.command == "run":
        if not args.fixture and not args.allow_models:
            parser.error("Real autonomy requires --allow-models and the frozen authorized model budget")
        if args.max_steps is not None and args.max_steps < 1 or not 0 <= args.wait_seconds <= 86400:
            parser.error("Invalid run bounds")
        worker = FixtureWorker() if args.fixture else NativeWorker()
        deadline = time.monotonic() + args.wait_seconds
        while True:
            result = Research(args.project, worker).run(max_steps=args.max_steps)
            print(json.dumps(status(args.project), ensure_ascii=False), flush=True)
            if result["status"] != "waiting_for_gateway" or time.monotonic() >= deadline:
                break
            time.sleep(min(30, max(0, deadline - time.monotonic())))
    print(json.dumps(status(args.project), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
