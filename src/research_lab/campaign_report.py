"""Evidence-derived claims, deterministic writing, and independently recomputed audit."""

import random
import statistics

from .agents import assess_candidate
from .report import summarize, tex_escape
from .storage import read_json, write_json, write_text


def _interval(values):
    rng = random.Random(20260929)
    samples = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(2000))
    return [samples[49], samples[1949]]


def evidence_claims(root):
    from .campaign import checked_results
    protocol = read_json(root / "inputs" / "protocol.json")
    plan = read_json(root / "inputs" / "plans" / "holdout.json")
    rows = checked_results(root / "runs" / "holdout")
    summary = summarize(plan, rows)
    baseline = {row["seed"]: row for row in rows if row["method"] == protocol["baseline"]}
    claims = []
    for item in summary["methods"]:
        selected = [row for row in rows if row["method"] == item["method"]]
        deltas = [row["result"]["metrics"][summary["metric"]] -
                  baseline[row["seed"]]["result"]["metrics"][summary["metric"]] for row in selected]
        supporting = list({row["result_path"]: row for row in selected + list(baseline.values())}.values())
        claims.append({"id": f"holdout_{item['method']}", "split": "holdout", **item,
                       "metric": summary["metric"], "paired_delta_bootstrap_95": _interval(deltas),
                       "evidence": [{"path": "runs/holdout/" + row["result_path"], "sha256": row["sha256"]}
                                    for row in supporting]})
    return {"schema_version": 1, "claims": claims,
            "uncertainty": "Percentile bootstrap over paired seed means, 2000 resamples, fixed RNG. Exploratory; few seeds and synthetic data limit inference. Not adjusted for development search or a significance test."}, summary


def render_paper(protocol, selection, claims, history, registry):
    lines = [f"# {protocol['title']}", "",
             "> LOCAL V2 ENGINEERING DRAFT. Rule-driven search and deterministic writing; no LLM. Not competition-ready.", "",
             "## Abstract", "",
             f"We evaluate preregistered methods for: {protocol['question']} "
             f"Development search selected `{selection['method']}` in {len(history)} trials. "
             "The selected method was frozen before evaluation on disjoint holdout seeds. "
             "The results below describe this experiment only; novelty and real-agent transfer are unverified.", "",
             "## Question and hypothesis", "", protocol["question"], "", protocol["hypothesis"], "",
             "## Protocol", "",
             f"Baseline: `{protocol['baseline']}`. Candidate order: {', '.join(protocol['candidates'])}. "
             f"Ablations: {', '.join(protocol['ablations'])}. "
             f"Development seeds: {protocol['development_seeds']}; holdout seeds: {protocol['holdout_seeds']}. "
             f"Metric: {protocol['primary_metric']} ({protocol['direction']}). "
             f"Required development improvement: {protocol['search']['min_improvement']}. "
             "Ties retain the incumbent. Holdout scores never feed back into selection.", "",
             "## Development decisions", "",
             "| Candidate | Mean | Improvement over incumbent | Decision |", "|---|---:|---:|---|"]
    for item in history:
        lines.append(f"| {item['candidate']} | {item['score']:.6f} | {item['improvement']:+.6f} | {item['decision']} |")
    lines += ["", f"Search stop: {selection['stop_reason']}.", "", "## Holdout results", "",
              "| Method | Mean | Sample SD | Paired delta | Exploratory 95% interval | Evidence claim |",
              "|---|---:|---:|---:|---|---|"]
    for claim in claims["claims"]:
        low, high = claim["paired_delta_bootstrap_95"]
        lines.append(f"| {claim['method']} | {claim['mean']:.6f} | {claim['sample_stddev']:.6f} | "
                     f"{claim['paired_delta_mean']:+.6f} | [{low:+.6f}, {high:+.6f}] | `{claim['id']}` |")
    selected = next(item for item in claims["claims"] if item["method"] == selection["method"])
    sign = 1 if protocol["direction"] == "maximize" else -1
    outcome = "better than" if sign * selected["paired_delta_mean"] > 0 else "worse than" if sign * selected["paired_delta_mean"] < 0 else "equal to"
    lines += ["", f"The frozen selection was {outcome} the baseline on the configured holdout metric "
              f"(raw paired delta {selected['paired_delta_mean']:+.6f}; claim `{selected['id']}`). "
              "A negative result does not trigger reselection.", "", claims["uncertainty"], "",
              "## Evidence and resources", "",
              "claims.json maps each holdout row to hashed raw results. selection.json records the frozen choice. "
              "resource_report.json includes failed attempts and conservative budget reservations. "
              "Human contributions: protocol, trusted experiment implementations, sources and search space. "
              "Automatic contributions: execution, development decisions, descriptive analysis, draft and consistency checks.", "",
              "## Limitations", ""]
    lines += [f"- {value}" for value in protocol["limitations"]]
    lines += ["- Disjoint seeds prevent direct seed reuse, but do not establish distributional independence or external validity.",
              "- This local report does not validate literature relevance, novelty, or research significance.", "",
              "## Source registry", ""]
    if registry:
        lines += [f"- [{item['id']}] {item['title']}. {item['url'] or 'Local document'}. "
                  f"Snapshot: `{item['archived_path']}`. {item['note']} "
                  "(Snapshot integrity checked; source authenticity and relevance not independently verified.)" for item in registry]
    else:
        lines.append("No literature snapshots supplied. Literature review and novelty assessment remain pending.")
    return "\n".join(lines) + "\n"


def generate_campaign_reports(root, protocol, state):
    claims, summary = evidence_claims(root)
    selection = read_json(root / "selection.json")
    registry = read_json(root / "inputs" / "source_registry.json")
    write_json(root / "claims.json", claims)
    write_json(root / "summary.json", summary)
    write_json(root / "search_history.json", [{k: v for k, v in item.items() if k != "manifest"} for item in state["history"]])
    paper = render_paper(protocol, selection, claims, state["history"], registry)
    write_text(root / "paper_draft.md", paper)
    # A reviewable TeX source, explicitly not an ICLR template or compiled PDF.
    paragraphs = []
    for line in paper.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            paragraphs.append(r"\section{" + tex_escape(line[3:]) + "}")
        elif line:
            paragraphs.append(tex_escape(line) + r"\par")
    write_text(root / "paper_draft.tex", "\n".join([
        r"\documentclass{article}", r"\usepackage[margin=1in]{geometry}",
        r"\title{" + tex_escape(protocol["title"]) + "}", r"\author{Local engineering draft}",
        r"\begin{document}\maketitle", "Article-class source; not official ICLR format. PDF compilation is not validated.",
        *paragraphs, r"\end{document}", ""]))
    records = [read_json(path) for path in root.glob("runs/*/jobs/*/attempt_*/execution.json")]
    resources = {"mode": "offline-rules", "orchestrator_model_calls": 0, "orchestrator_model_tokens": 0,
                 "attempt_records": len(records), "failed_or_interrupted_attempts": sum(x["status"] != "completed" for x in records),
                 "measured_subprocess_seconds": sum(x.get("wall_seconds", 0) for x in records),
                 "budget_reservations": len(state["budget"]["reservations"]),
                 "reserved_timeout_seconds": sum(x["timeout_seconds"] for x in state["budget"]["reservations"]),
                 "limits": protocol["budget"], "billing_cost": None,
                 "note": "Reservations include retries and are never refunded; crash windows may reserve without launch. Timeout allocation is not elapsed wall time. Experiment-internal model use is self-reported in raw provenance."}
    write_json(root / "resource_report.json", resources)
    write_text(root / "resource_report.md", "# Resource report\n\n" + "\n".join(f"- {k}: {v}" for k, v in resources.items()) + "\n")
    review = {"reviewer": "local-rule-critic-v2", "external_review": False,
              "findings": [
                  {"severity": "blocking_submission", "issue": "Novelty and literature need human verification", "action": "Add relevant published sources with local snapshots and assess novelty"},
                  {"severity": "blocking_submission", "issue": "No official ICLR PDF / external Reviewer token", "action": "Prepare and inspect official-format PDF, then obtain matching Reviewer response"},
                  {"severity": "limitation", "issue": "Synthetic experiment and limited seed repeats", "action": "Preregister real task evaluation and stronger baselines in a new campaign"},
                  {"severity": "integration", "issue": "Full SwarmFlow runtime and model roles are unvalidated", "action": "Configure services and isolate generated code before enabling model-driven experiments"}],
              "engineering_audit": "See audit.json; consistency checks are not scientific peer review"}
    write_json(root / "review.json", review)
    write_text(root / "revision_plan.md", "# Revision plan\n\nGenerated by a local rule checker, not external peer review.\n\n" +
               "\n".join(f"- [{item['severity']}] {item['issue']}: {item['action']}" for item in review["findings"]) +
               "\n\nAny change to candidates, data, primary metric or hypotheses requires a new campaign; do not overwrite the frozen holdout result.\n")


def audit_campaign_content(root):
    from .campaign import checked_results
    errors = []
    try:
        protocol = read_json(root / "inputs" / "protocol.json")
        state = read_json(root / "state.json")
        selection = read_json(root / "selection.json")
        incumbent, score = protocol["baseline"], None
        data_ids = {}
        from .agents import LocalPlanner
        prior = []
        for item in state["history"]:
            expected_candidate = LocalPlanner().propose(protocol["candidates"], prior,
                max_trials=protocol["search"]["max_trials"], patience=protocol["search"]["patience"])
            if item["candidate"] != expected_candidate:
                errors.append("Development candidate order violates preregistered planner")
            grid = root / item["grid"]
            plan = read_json(grid / "inputs" / "plan.json")
            rows = checked_results(grid)
            if plan["seeds"] != protocol["development_seeds"] or plan["methods"] != [protocol["baseline"], item["candidate"]]:
                errors.append("Development grid differs from protocol")
            summary = summarize(plan, rows)
            decision = assess_candidate(item["candidate"], summary, incumbent, score, protocol["search"]["min_improvement"])
            if any(item.get(k) != v for k, v in decision.items()):
                errors.append("Development decision is not supported by raw results")
            if decision["accepted"]:
                incumbent, score = decision["candidate"], decision["score"]
            elif score is None:
                score = decision["previous_score"]
            prior.append(decision)
            for row in rows:
                seed, checksum = row["seed"], row["result"]["provenance"]["dataset_sha256"]
                if seed in data_ids and data_ids[seed] != checksum:
                    errors.append("Development dataset identity mismatch")
                data_ids[seed] = checksum
        if not prior or selection["method"] != incumbent or selection["development_score"] != score or selection["trials"] != len(prior):
            errors.append("Frozen selection is not supported by development evidence")
        expected_methods = list(dict.fromkeys([protocol["baseline"], incumbent, *protocol["ablations"]]))
        holdout_plan = read_json(root / "runs" / "holdout" / "inputs" / "plan.json")
        if selection["holdout_methods"] != expected_methods or holdout_plan["methods"] != expected_methods or holdout_plan["seeds"] != protocol["holdout_seeds"]:
            errors.append("Holdout grid differs from frozen protocol")
        holdout_rows = checked_results(root / "runs" / "holdout")
        if set(protocol["development_seeds"]) & set(protocol["holdout_seeds"]):
            errors.append("Development/holdout seed leakage")
        if set(data_ids.values()) & {row["result"]["provenance"]["dataset_sha256"] for row in holdout_rows}:
            errors.append("Development/holdout dataset identity reused")
        claims, summary = evidence_claims(root)
        if read_json(root / "claims.json") != claims or read_json(root / "summary.json") != summary:
            errors.append("Numerical claims differ from raw evidence")
        paper = render_paper(protocol, selection, claims, state["history"], read_json(root / "inputs" / "source_registry.json"))
        if (root / "paper_draft.md").read_text(encoding="utf-8") != paper:
            errors.append("Draft differs from evidence-derived deterministic text")
        budget = state["budget"]
        if budget["max_attempts"] != protocol["budget"]["max_attempts"] or budget["max_timeout_seconds"] != protocol["budget"]["max_timeout_seconds"]:
            errors.append("Budget limits changed")
        if len(budget["reservations"]) > budget["max_attempts"] or sum(x["timeout_seconds"] for x in budget["reservations"]) > budget["max_timeout_seconds"]:
            errors.append("Budget exceeded")
        attempts = list(root.glob("runs/*/jobs/*/attempt_*/execution.json"))
        if len(attempts) > len(budget["reservations"]):
            errors.append("Unreserved executions found")
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, StopIteration) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors,
            "scope": "Recompute selection, holdout statistics, claim sources and deterministic draft; not a novelty or peer-review score"}
