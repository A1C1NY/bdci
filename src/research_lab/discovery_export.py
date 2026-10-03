"""Evidence-only manuscript and discovery audit export for open-topic campaigns."""
import html
import json
import shutil
import subprocess
import time

from .report import tex_escape
from .storage import write_json, write_text


def export(folder, config, state, sources):
    draft, analysis = state["draft"], state["analysis"]
    fixture = state["fixture_only"]
    scope = state["frozen"]["capability"]["scope"]
    criterion = analysis["ci95"][0] > config["min_gain"]
    result = (f"For {analysis['n']} evaluation units, baseline {analysis['metric']} was {analysis['baseline']:.6f}, "
              f"selected-method score {analysis['candidate']:.6f}. Paired difference: {analysis['gain']:+.6f}; "
              f"95% paired bootstrap interval [{analysis['ci95'][0]:+.6f}, {analysis['ci95'][1]:+.6f}]. "
              + ("The prespecified metric gain criterion was met." if criterion else "The gain criterion was not established; this is a negative or inconclusive result."))
    methods = ("Topic selection used literature and declared capabilities, followed by two model reviewers. "
        "The first approved highest-priority topic was frozen before experiments; no topic was selected using formal evaluation scores. "
        f"Asset: {config['id']}. Prior exposure: {config['data_exposure']}. Provenance: {config['provenance']}. "
        f"Declared independent unit: {config['unit_of_analysis']}. "
        f"Baseline: {json.dumps(config['baseline'], sort_keys=True)}. Selected method: {json.dumps(state['frozen']['selected'], sort_keys=True)}. "
        f"Up to {config['max_candidates']} development candidates with strict improvement > {config['min_gain']} were allowed. "
        "The frozen baseline and selected method were evaluated once. Intervals use 10000 paired unit-bootstrap samples with seed 20261003. "
        + ("All learned weights, feature means and scales use the training split only. " if config["domain"] == "tabular_classification" else
           f"Retrieval contexts have a {config['context_bytes']}-byte ceiling. "))
    limits = (scope + " " + ("This entire report is a synthetic software fixture, not scientific evidence. " if fixture else "")
        + "Literature search is bounded and incomplete; metadata and abstracts are not verified full texts. "
        "Gap and novelty assessments are model hypotheses, not established novelty. "
        "Machine review consensus can contain correlated errors; it is not human peer review or a venue score. "
        "Source quotation matching does not prove entailment. Dataset independence and licenses were declared, not independently certified. "
        + draft["limitations"])
    sections = [("Abstract", draft["abstract"]), ("Introduction", draft["introduction"]), ("Methods", methods),
                ("Results", result), ("Discussion", draft["discussion"]), ("Limitations", limits)]
    sections = [(heading, text.replace("{{primary_result}}", result)) for heading, text in sections]
    refs = [s for s in sources if s["id"] in draft["citations"]]
    md = ["# " + draft["title"], "", "> Machine-reviewed research draft; not externally submitted.", ""]
    for title, text in sections:
        md.extend(["## " + title, "", text, ""])
    md.extend(["## References", "", *[f"- [{s['id']}] {s['title']} ({s['evidence_level']}): {s['url']}" for s in refs]])
    write_text(folder / "paper_draft.md", "\n".join(md))
    write_text(folder / "paper.html", "<!doctype html><meta charset='utf-8'><title>Research draft</title>"
        "<style>body{max-width:850px;margin:40px auto;font:18px/1.6 Georgia;padding:0 20px}</style><h1>"
        + html.escape(draft["title"]) + "</h1>" + "".join("<h2>" + heading + "</h2><p>" + html.escape(text) + "</p>" for heading, text in sections)
        + "<h2>References</h2>" + "".join("<p>" + html.escape(s["title"] + " — " + s["url"] + " (" + s["evidence_level"] + ")") + "</p>" for s in refs))
    tex = [r"\documentclass{article}", r"\usepackage[T1]{fontenc}", r"\usepackage[utf8]{inputenc}",
           r"\usepackage[margin=1in]{geometry}", r"\usepackage{hyperref}", r"\title{" + tex_escape(draft["title"]) + "}",
           r"\author{Autonomous Research System}", r"\begin{document}\maketitle"]
    for heading, text in sections:
        tex.extend([r"\section*{" + heading + "}", tex_escape(text)])
    tex.append(r"\section*{References}")
    tex.extend(tex_escape(s["title"] + " — " + s["url"] + " (" + s["evidence_level"] + ")") + r"\par" for s in refs)
    tex.append(r"\end{document}")
    write_text(folder / "paper.tex", "\n".join(tex))
    pdf_status = "not_requested"
    if config.get("compile_pdf"):
        binary = shutil.which("pdflatex")
        pdf_status = "compiler_unavailable" if not binary else "compiled"
        if binary:
            for i in range(2):
                try:
                    p = subprocess.run([binary, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "paper.tex"],
                        cwd=folder, capture_output=True, timeout=max(1, min(60, state["deadline"] - time.time())))
                    (folder / f"latex-{i}.log").write_bytes(p.stdout + p.stderr)
                    if p.returncode or not (folder / "paper.pdf").exists():
                        pdf_status = "compile_failed"
                        break
                except subprocess.TimeoutExpired:
                    pdf_status = "compile_timeout"
                    break
    write_json(folder / "claims.json", {"analysis": analysis, "scope": scope, "gain_criterion_met": criterion,
        "criterion": "paired lower 95% bound > frozen min_gain", "novelty_established": False,
        "fixture_only": fixture, "ready_for_external_submission": False, "data_exposure": config["data_exposure"]})
    write_json(folder / "topic_audit.json", {"selected": state["selected_topic"], "all_candidates": state["topic_pool"],
        "rule": "Feasibility and dual reviews, then director priority; no evaluation scores", "source_levels": {s["id"]: s["evidence_level"] for s in sources}})
    write_json(folder / "resource_report.json", {"charged_or_reserved": state["charged_or_reserved"],
        "model_calls": state["model_calls"], "worker_calls": state["worker_calls"], "fixture_only": fixture,
        "coverage": "Single shared allowance includes discovery, reviews, experiments and writing; original model ledger remains authoritative"})
    write_json(folder / "review_audit.json", state["reviews"])
    write_json(folder / "protocol.json", state["frozen"])
    write_text(folder / "REPRODUCE.md", "# Reproduction\n\nPreserve this complete private project and its pinned source checkout. "
        "Sources, assets and completed operations are hash verified. Raw model records are in outputs/v4-<native_stage>. "
        "Keep the original ledger and unknown reservations.\n\nResume: `python -m research_lab discover run <project> "
        + ("--fixture" if fixture else "--allow-models") + "`. A completed resume makes no new calls. "
        "Never reopen topic selection after formal evaluation.\n")
    return {"paper_source": "paper.tex", "pdf_status": pdf_status, "fixture_only": fixture,
        "ready_for_external_submission": False, "scientific_success_not_implied": True,
        "research_outcome": "fixture_only" if fixture else "metric_gain_supported" if criterion else "inconclusive_or_negative"}
