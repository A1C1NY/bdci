"""Topic-independent ICLR builder from validated prose, evidence and tables."""
import re
import os
import shutil
import subprocess
from pathlib import Path
from .report import tex_escape
from .storage import write_json, digest
from .framework import ROOT
from jiuwenswarm.common.research_runtime import evidence_gate


def compile_document(document, output, *, tex_binary=None):
    tex_binary = tex_binary or os.environ.get("RESEARCH_LAB_TEX_BINARY", "pdflatex")
    if not shutil.which(tex_binary):
        raise RuntimeError("TeX executable unavailable; set RESEARCH_LAB_TEX_BINARY or pass tex_binary")
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    evidence_gate(document["claims"],document["evidence"])
    claims={c["id"]:c["text"] for c in document["claims"]}
    references={r["id"]:r for r in document["references"]}
    def prose(text):
        def substitute(m):
            if m[1] not in claims:raise ValueError("Unknown numerical claim "+m[1])
            return claims[m[1]]
        text=re.sub(r"\{\{([A-Za-z0-9_]+)\}\}",substitute,text)
        if "{{" in text or "}}" in text:raise ValueError("Unresolved claim marker")
        text=text.translate(str.maketrans({"–":"-","—":"-","‑":"-","’":"'","“":'"',"”":'"',"α":"alpha","β":"beta"}))
        pieces=re.split(r"(\[[a-z][a-z0-9_]*\])",text)
        result=[]
        for piece in pieces:
            if re.fullmatch(r"\[[a-z][a-z0-9_]*\]",piece):
                key=piece[1:-1]
                if key not in references:raise ValueError("Unknown citation "+key)
                result.append(r"\citep{"+key+"}")
            else:result.append(tex_escape(piece))
        return "".join(result)
    for p in (ROOT/"references/templates/iclr2026").glob("*.sty"):
        shutil.copyfile(p,output/p.name)
    lines=[r"\documentclass{article}",r"\usepackage{iclr2026_conference,times}",r"\usepackage[T1]{fontenc}",
           r"\usepackage[utf8]{inputenc}",r"\usepackage{graphicx,booktabs,longtable,amsmath,amssymb,hyperref,url}",
           r"\title{"+tex_escape(document["title"])+"}",r"\author{"+tex_escape(document["author"])+"}",
           r"\iclrfinalcopy\begin{document}\maketitle",
           r"\lhead{CCF BDCI 2026 competition manuscript; not an ICLR submission}",r"\begin{abstract}",
           prose(document["abstract"]),r"\end{abstract}"]
    for section in document["sections"]:
        if section.get("appendix"):lines.append(r"\appendix")
        lines.append(r"\section{"+tex_escape(section["heading"])+"}")
        for paragraph in section.get("paragraphs",[]):lines.extend([prose(paragraph),""])
        for table in section.get("tables",[]):
            lines.extend([r"\begin{table}[ht]\centering\small",r"\caption{"+prose(table["caption"])+"}",
                          r"\begin{tabular}{"+"l"+"r"*(len(table["headers"])-1)+"}",r"\toprule",
                          " & ".join(tex_escape(x) for x in table["headers"])+r"\\\midrule"])
            lines.extend(" & ".join(tex_escape(x) for x in row)+r"\\" for row in table["rows"])
            lines.extend([r"\bottomrule\end{tabular}\end{table}"])
        for figure in section.get("figures",[]):
            source=Path(figure["path"])
            shutil.copyfile(source,output/source.name)
            lines.extend([r"\begin{figure}[ht]\centering",r"\includegraphics[width=\linewidth]{"+source.name+"}",
                          r"\caption{"+prose(figure["caption"])+r"}\end{figure}"])
    lines.append(r"\begin{thebibliography}{9}")
    for ref in document["references"]:
        lines.append(r"\bibitem["+tex_escape(ref["short"])+"]{"+ref["id"]+"} "+prose(ref["text"])+r" \url{"+ref["url"]+"}.")
    lines.extend([r"\end{thebibliography}",r"\end{document}"])
    (output/"paper.tex").write_text("\n".join(lines),"utf-8")
    write_json(output/"document.json",document)
    for i in range(2):
        completed=subprocess.run([tex_binary,"-interaction=nonstopmode","-halt-on-error","paper.tex"],cwd=output,capture_output=True)
        (output/f"build-{i+1}.log").write_bytes(completed.stdout+completed.stderr)
        if completed.returncode:raise RuntimeError("LaTeX failed; inspect build log")
    write_json(output/"build_manifest.json",{"pdf_sha256":digest(output/"paper.pdf"),"document_sha256":digest(output/"document.json"),
               "tex_sha256":digest(output/"paper.tex"),"evidence_verified":True})
    return output/"paper.pdf"
