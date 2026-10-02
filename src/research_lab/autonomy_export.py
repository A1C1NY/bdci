"""Evidence-derived English manuscript sources and reproducible local handoff."""
import html
import json
from pathlib import Path
import shutil
import subprocess

from .report import tex_escape
from .storage import digest, read_json, write_json, write_text


def export(folder, config, state, sources):
    draft, analysis = state["draft"], state["analysis"]
    fixture = config["domain"] == "fixture_threshold"
    scope = "Synthetic software validation; not scientific evidence." if fixture else (
        "Bounded STALE retrieval study. The endpoint is literal update inclusion, not reader answer quality. "
        "The method family and data assets were supplied at initialization; this is not unrestricted autonomous discovery.")
    supported = analysis["ci95"][0] > config["min_gain"]
    result = (f"On {analysis['n']} evaluation scenarios, baseline score was {analysis['baseline']:.6f} and "
              f"selected-method score was {analysis['candidate']:.6f}. The paired difference was {analysis['gain']:+.6f}, "
              f"with a 95% scenario-bootstrap interval [{analysis['ci95'][0]:+.6f}, {analysis['ci95'][1]:+.6f}]. "
              + ("The prespecified gain criterion was met for this metric only." if supported else
                 "The prespecified gain criterion was not established; this result is negative or inconclusive."))
    methods = (f"Selection used development data only and a strict improvement threshold of {config['min_gain']}. "
               f"At most {config['max_candidates']} candidates were permitted. Baseline: {json.dumps(config['baseline'], sort_keys=True)}. "
               f"Frozen selection: {json.dumps(state['frozen']['selected'], sort_keys=True)}. "
               f"Prior exposure: {config['data_exposure']}. Evaluation compared the frozen baseline and selected method once. "
               "Intervals used 10,000 paired scenario bootstrap samples and fixed seed 20261003. "
               f"Retrieval contexts use a {config['context_bytes']}-byte ceiling where applicable.")
    limits = (scope + " Data declared unseen to this workflow is not certified unseen globally. "
              "Machine reviews are model opinions, not human peer review; correlated errors remain possible. "
              "Quoted-source matching proves text presence, not semantic support or novelty. " + draft["limitations"])
    sections = [("Abstract", draft["abstract"]), ("Introduction", draft["introduction"]),
                ("Methods", methods), ("Results", result), ("Discussion", draft["discussion"]), ("Limitations", limits)]
    sections = [(heading, text.replace("{{primary_result}}", result)) for heading, text in sections]
    refs = [s for s in sources if s["id"] in draft["citations"]]
    md = ["# " + draft["title"], "", "> Machine-reviewed manuscript source. No external submission or venue score.", ""]
    for title, text in sections:
        md.extend(["## " + title, "", text, ""])
    md.extend(["## References", "", *[f"- [{s['id']}] {s['title']}: {s['url']}" for s in refs]])
    write_text(folder / "paper_draft.md", "\n".join(md) + "\n")
    body = "".join(f"<h2>{title}</h2><p>{html.escape(text)}</p>" for title, text in sections)
    write_text(folder / "paper.html", "<!doctype html><meta charset='utf-8'><title>Research manuscript</title>"
               "<style>body{max-width:850px;margin:40px auto;font:18px/1.6 Georgia;padding:0 20px}h1{line-height:1.2}</style>"
               + "<h1>" + html.escape(draft["title"]) + "</h1>" + body + "<h2>References</h2>" +
               "".join("<p>" + html.escape(s["title"] + " — " + s["url"]) + "</p>" for s in refs))
    # Only verified official templates are allowed; model text is always escaped.
    repo = Path(__file__).resolve().parents[2]
    assets = read_json(repo / "config/assets.json")["iclr"]
    styles = [x for x in assets if x["path"].endswith(".sty")]
    iclr = bool(styles) and all((repo / x["path"]).is_file() and digest(repo / x["path"]) == x["sha256"] for x in styles)
    if iclr:
        for item in styles:
            shutil.copyfile(repo / item["path"], folder / Path(item["path"]).name)
    tex = [r"\documentclass{article}", r"\usepackage[T1]{fontenc}", r"\usepackage[utf8]{inputenc}",
           r"\usepackage{hyperref}", r"\usepackage{iclr2026_conference,times}" if iclr else r"\usepackage[margin=1in]{geometry}",
           r"\title{" + tex_escape(draft["title"]) + "}", r"\author{Autonomous Research System}",
           r"\begin{document}\maketitle"]
    for title, text in sections:
        tex.extend([r"\section*{" + title + "}", tex_escape(text)])
    tex.append(r"\section*{References}")
    for item in refs:
        tex.extend([tex_escape(item["title"] + " — " + item["url"]), r"\par"])
    tex.append(r"\end{document}")
    write_text(folder / "paper.tex", "\n".join(tex))
    pdf_status = "not_requested"
    if config.get("compile_pdf", False):
        executable = shutil.which("pdflatex")
        if executable is None:
            pdf_status = "compiler_unavailable"
        else:
            pdf_status = "compiled"
            for i in range(2):
                try:
                    p = subprocess.run([executable, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "paper.tex"],
                                       cwd=folder, capture_output=True, timeout=60)
                    (folder / f"latex-{i}.log").write_bytes(p.stdout + p.stderr)
                    if p.returncode or not (folder / "paper.pdf").is_file():
                        pdf_status = "compile_failed"
                        break
                except subprocess.TimeoutExpired:
                    pdf_status = "compile_timeout"
                    break
    claims = {"analysis": analysis, "scope": scope, "gain_criterion_met": supported,
              "criterion": "paired lower 95% bound > frozen min_gain", "data_exposure": config["data_exposure"],
              "evidence_operations": ["baseline-evaluation", "selected-evaluation", "analysis"],
              "novelty_established": False, "reader_accuracy_established": False}
    write_json(folder / "claims.json", claims)
    write_json(folder / "resource_report.json", {"charged_or_reserved": state["charged_or_reserved"],
               "model_call_intents": state["model_calls"], "worker_calls": state["worker_calls"],
               "backend": state["worker_identity"]["backend"], "fixture_only": fixture})
    write_json(folder / "review_audit.json", state["reviews"])
    write_json(folder / "protocol.json", state["frozen"])
    write_text(folder / "REPRODUCE.md", "# Reproduction\n\nPreserve the entire project, input snapshots and original model ledger. "
               "Do not publish private snapshots or credentials. Use the exact implementation hashes in autonomy-state.json.\n\n"
               "Resume without duplicate model calls:\n\n`python -m research_lab autonomous run <project> "
               + ("--fixture" if fixture else "--allow-models") + "`\n\n"
               "A completed run verifies artifacts and returns; it does not search again on evaluation results. "
               "Create a new disclosed protocol for new research. For an independent replication, initialize a new ID. "
               "Native raw requests and responses are in outputs/v4-<native_stage>, as recorded for every paid operation "
               "in autonomy-state.json; preserve them privately with this project.\n")
    return {"paper_source": "paper.tex", "pdf_status": pdf_status, "iclr_template_verified": iclr,
            "fixture_only": fixture, "ready_for_external_submission": False,
            "research_outcome": "metric_gain_supported" if supported and not fixture else "fixture_only" if fixture else "inconclusive_or_negative",
            "scientific_success_not_implied": True}
