"""Bind supervisor-reviewed model prose to executable evidence, then compile."""
from collections import defaultdict
import copy
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,digest
from research_lab.manuscript import compile_document

BASE=ROOT/"research/v4"
NAMES={"bm25":"BM25","recent":"Recent","bm25_recent":"BM25 + time","change_candidate":"BM25 + time + cue","temporal_candidate":"High time (rejected)"}


def build(output_dir=None):
    raw=read_json(BASE/"model-sections-core.json")
    approved=copy.deepcopy(raw)
    pairs=read_json(BASE/"paired.json")
    rows=read_json(BASE/"heldout-rows.json")
    def comparison(policy,control="bm25",budget=4096):
        return next(r for r in pairs if r["policy"]==policy and r["control"]==control and r["budget"]==budget)
    def estimate(row):return f"{100*row['delta']:+.2f} percentage points (95% interval {100*row['ci95'][0]:+.2f} to {100*row['ci95'][1]:+.2f})"
    texts={"C_primary":estimate(comparison("change_candidate")),
           "C_incremental":estimate(comparison("change_candidate","bm25_recent")),
           "C_highrecency":estimate(comparison("temporal_candidate")),
           "C_budget":estimate(comparison("change_candidate",budget=8192))}
    evpaths={"protocol":BASE/"frozen.json","retrieval":BASE/"heldout-rows.json","paired":BASE/"paired.json"}
    for entry in read_json(BASE/"literature/registry.json"):evpaths[entry["id"]]=ROOT/entry["path"]
    evidence={k:{"path":str(p),"sha256":digest(p)} for k,p in evpaths.items()}
    claims=[{"id":key,"text":value,"evidence_ids":["paired","retrieval","protocol"]} for key,value in texts.items()]
    # Explicit supervisor edits. Raw model drafts remain unmodified on disk.
    intro=approved["introduction"]["paragraphs"]
    intro[2]=intro[2].replace("extracted from the query","detected in each candidate user turn").replace("a frozen development protocol","a bounded development procedure")
    intro[3]="The frozen candidate improves update inclusion over BM25 by {{C_primary}} at the primary budget. Its incremental advantage over the temporal baseline is only {{C_incremental}}. The interval includes zero, so this experiment does not establish a separate benefit of the lexical change cue. High recency weighting and a pure trailing window are retained as negative controls; the former reduces retrieval quality and the latter is sensitive to where STALE inserts update sessions."
    intro[4]="We separate update-statement inclusion from downstream response quality. A paired pilot applies two independent reader routes and the official three-dimensional grading rubric to frozen retrieved contexts on a small held-out subset. The contribution is a transparent external-benchmark audit and its executable research record, with supervised candidate acceptance and rejection. It is not a claim of architectural novelty or state-of-the-art agent memory."
    related=approved["related_work"]["paragraphs"]
    related[0]=related[0].replace(", which the original paper does not isolate","")
    related[1]="STALE's CUPMem combines structured memory consolidation, invalidation and premise verification [stale]. These mechanisms are substantially richer than our sparse selector and are not reimplemented or compared numerically. TANGLE studies personal memories with irreducible conflict [tangle]; TRACE studies validity in evolving multi-agent systems [trace]. They motivate careful interpretation of memory validity, but our one-dataset audit does not evaluate their settings."
    related[2]="Our lexical scorer follows the standard BM25 family [bm25]. Temporal weighting and lexical change markers are simple heuristics, not new algorithms. LongMemEval studies long-term interactive memory, including temporal reasoning and knowledge updates [longmemeval]; STALE reuses LongMemEval dialogue material as distractors. We isolate a raw-user-turn retrieval condition and report its limitations rather than comparing against incompatible published full-context scores."
    results=approved["retrieval_results"]["paragraphs"]
    results[0]="Table 1 reports normalized verbatim containment of new states, with all three questions averaged within each held-out scenario. The full evaluation comprises five selectors, two byte ceilings, and the same scenario/query pairs. All methods use the same candidate pool and whole-turn byte accounting. Old-state retrieval is a diagnostic, not automatically an error: a reader may need the old and new statements to understand an update."
    results[1]="The primary paired comparison is {{C_primary}}. Uncertainty resamples complete scenarios, keeping their three related questions together. This supports a moderate availability gain over our plain BM25 implementation. It does not demonstrate improved answer correctness, causal transfer, or superiority to dense or learned retrieval."
    results[2]="The development-rejected high-time candidate remains in the diagnostic evaluation. Its held-out comparison against BM25 is {{C_highrecency}}, confirming that stronger recency is not uniformly beneficial in this construction. The selected candidate's descriptive comparison at the larger byte budget is {{C_budget}}. Secondary comparisons are not treated as multiplicity-adjusted discoveries."
    results[3]="The incremental comparison against the fixed time-weighted baseline is {{C_incremental}}. This interval crosses zero. The combined selector's improvement over BM25 must therefore not be presented as a demonstrated standalone contribution of the change marker. Figure 1 separates retained old and new statements across policies and budgets."
    audit_path=BASE/"replay-audit.json"
    if audit_path.exists():
        audit=read_json(audit_path)
        evidence["replay"]={"path":str(audit_path),"sha256":digest(audit_path)}
        ceiling=f"{audit['verbatim_recoverable_scenarios']}/{audit['heldout_scenarios']} held-out scenarios ({100*audit['verbatim_recoverable_scenarios']/audit['heldout_scenarios']:.2f} percent) contain a normalized verbatim new-state statement somewhere in the full user-turn pool. The remaining scenarios remain in the evaluation denominator."
        claims.append({"id":"C_ceiling","text":ceiling,"evidence_ids":["replay","protocol"]})
        results.append("An offline replay verifies every retrieval record and reader context. {{C_ceiling}} A missing exact match can coexist with semantically sufficient paraphrases, so containment is an availability diagnostic rather than a necessary or sufficient condition for a correct answer.")
    approved["limitations"]["heading"]="Limitations"
    approved["limitations"]["paragraphs"][-1]="The reader pilot uses gateway model aliases whose underlying weights and revisions are not independently authenticated. Opposite-model grading reduces direct self-grading but remains a fallible model judgment, and reader and judge effects are coupled. The small sample, missing requests and absence of human labels prevent strong conclusions about answer accuracy. We report all attempted requests and retain unknown-usage reservations. No retrieval parameters are changed after seeing held-out or reader outcomes."
    approved["method"]["paragraphs"].append("For each candidate turn, the change feature is one if the case-insensitive word-boundary regular expression matches any listed marker, and zero otherwise. N is the number of indexed user turns and i is its zero-based chronological position. This use of position differs from elapsed wall-clock time. A turn that does not fit the remaining budget is skipped, allowing lower-ranked smaller turns to fill the budget. Full serialized contexts and their hashes are retained for reader provenance.")
    approved["method"]["paragraphs"].append("Bracketed session and turn headers are ordinary ordinal positions assigned to every history item, not the dataset's gold relevant-session annotations. They are excluded from BM25 token scoring but included in the byte cost and reader context. The separate chronological user-turn position contributes to the recency score. No gold update location is used for ranking.")
    approved["protocol"]["paragraphs"][0]=approved["protocol"]["paragraphs"][0].replace("primary confirmatory comparison","pre-frozen primary comparison").replace("seed20260929","seed 20260929")
    groups=defaultdict(list)
    for row in rows:groups[row["policy"],row["budget"]].append(row)
    table_rows=[]
    for name in NAMES:
        table_rows.append([NAMES[name]]+[f"{100*sum(r['new_present'] for r in groups[name,b])/len(groups[name,b]):.2f}" for b in (4096,8192)])
    import matplotlib;matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    fig,axs=plt.subplots(1,2,figsize=(7.4,3.0),sharey=True)
    short=["BM25","Recent","+time","+time+cue","High time"]
    for ax,budget in zip(axs,(4096,8192)):
        x=np.arange(5)
        for shift,field,label,color in [(-.17,"old_present","Old statement","#839bb6"),(.17,"new_present","New statement","#20796b")]:
            ax.bar(x+shift,[100*np.mean([r[field] for r in groups[p,budget]]) for p in NAMES],.34,label=label,color=color)
        ax.set_xticks(x,short,rotation=25,ha="right");ax.set_title(f"{budget} UTF-8 bytes");ax.set_ylim(0,85)
        ax.spines[["top","right"]].set_visible(False);ax.grid(axis="y",alpha=.15)
    axs[0].set_ylabel("Verbatim inclusion (%)");axs[1].legend(fontsize=8)
    fig.tight_layout();figure=BASE/"retrieval.png";fig.savefig(figure,dpi=220);plt.close(fig)
    sections=[]
    for key in ("introduction","related_work","method","protocol","retrieval_results"):
        sections.append({"heading":approved[key]["heading"],"paragraphs":approved[key]["paragraphs"]})
    sections[-1]["heading"]="Retrieval results"
    sections[-1]["tables"]=[{"caption":"Held-out new-statement inclusion (percent), averaged over three queries in each of 320 scenarios. High-time candidate was rejected on development. Recent-only is a construction-sensitive diagnostic.","headers":["Selector","4096 bytes","8192 bytes"],"rows":table_rows}]
    sections[-1]["figures"]=[{"path":str(figure),"caption":"Old versus updated statement inclusion on the same held-out scenarios. Retrieving an old statement alone does not constitute an answer error. Pure recent windows miss inserted update sessions under these budgets."}]
    reader_path=BASE/"reader-analysis.json"
    if reader_path.exists():
        reader=read_json(reader_path)
        evpaths["reader"]=reader_path;evidence["reader"]={"path":str(reader_path),"sha256":digest(reader_path)}
        texts["C_reader"]=reader["narrative"]
        claims.append({"id":"C_reader","text":reader["narrative"],"evidence_ids":["reader","protocol"]})
        missing_table={"caption":"All-attempt judged-pass bounds (percent), assigning every ungraded outcome to failure or success. These are missing-data bounds, not confidence intervals or validated human accuracy.","headers":["Reader","Selector","Lower","Upper"],"rows":[[r["model"],"BM25" if r["policy"]=="bm25" else "+time+cue",f"{100*r['all_attempts_lower_bound']:.1f}",f"{100*r['all_attempts_upper_bound']:.1f}"] for r in reader["aggregates"]]}
        sections.append({"heading":"Reader pilot","paragraphs":["{{C_reader}}",
            "The pilot uses the first 24 UIDs in the pre-frozen held-out list sorted by SHA-256 of the fixed seed prefix and UID. The original STALE rubric returns one Boolean pass for each of three query dimensions: explicit state probing, false-premise resistance and implicit task compliance. We average the three Boolean indicators within a scenario; there is no all-three-pass collapse. The paired contrast includes a scenario only when all three answers in both retrieval arms have grades, yielding 18 complete scenarios for DeepSeek and 20 for Kimi.",
            "The judge evaluates triples jointly. Eleven incomplete reader triples were not sent for judging: 11 failed answers and 22 otherwise valid answers therefore lack grades. All 85 submitted judge requests succeeded. Observed aggregate rates in Table 2 have unequal denominators; their unpaired difference is not the paired policy estimate reported above. Table 3 supplies pessimistic and optimistic bounds over all 72 attempted answers per model and selector.",reader["interpretation"]],"tables":[reader["table"],missing_table]})
    else:
        sections.append({"heading":"Reader pilot (intermediate draft)","paragraphs":["Reader requests are still running. This intermediate PDF is not a final research result or a submission candidate."]})
    sections.append({"heading":"Supervised research workflow","paragraphs":["The research run uses the pinned openJiuwen SwarmFlow engine, source-loaded through a modified JiuwenSwarm helper. A metered backend routes typed tasks to DeepSeek and Kimi through OpenAI-compatible endpoints. Native phase events, call signatures and journal records connect each task to its prompt, validated output and accounting record. This is a limited integration of the actual orchestration engine, not deployment of the full JiuwenSwarm service stack.","The supervisor rejects unsupported novelty claims, fixes the research question, reviews development evidence and freezes candidate selection. Workers emit schema-validated artifacts for critique, proposals, reader answers, judging and prose. Candidate changes are numeric configurations accepted by a trusted selector; generated arbitrary code is not executed. Persistent admission reserves worst-case route usage before each paid request. Completed requests can be reused, while uncertain requests retain their reservation and cannot be silently reissued. A writing-only recovery is separately recorded and does not replace failed scientific trials.","The scientific and engineering artifacts are distinct. Native replay tests verify resume behavior, and artifact hashes detect changed evidence; neither certifies the scientific validity of a claim. A generic document builder combines approved model-written prose, programmatically generated tables and an explicit claim-to-evidence registry. The same typed engine handles retrieval design and the separate reader question, but these are adjacent memory tasks rather than evidence of cross-domain autonomous research."]})
    sections.append({"heading":"Limitations","paragraphs":approved["limitations"]["paragraphs"]})
    sections.append({"heading":"Conclusion","paragraphs":["A context that looks relevant to a user query can still omit the statement that supersedes an older state. On the frozen STALE split, a modest temporal-and-cue selector improves verbatim update availability over plain BM25, while its incremental cue benefit over temporal scoring remains unresolved. Strong recency weighting fails. These results favor explicit availability diagnostics and paired reader evaluation over treating retrieval or workflow completion as proof of a capable memory system."]})
    sections.append({"heading":"Reproducibility and evidence boundaries","appendix":True,"paragraphs":["The release includes the UID split, fixed data version and licenses, source hashes, development proposals and decisions, per-query retrieval records, raw model responses, native journal/WAL records, usage summaries and an offline replay command. Public STALE data are distributed under CC BY 4.0; LongMemEval distractor material carries its supplied MIT notice. External data provenance does not by itself imply organizer acceptance of every use; the package states the sources explicitly.","Models receive selected user turns and one query per call. Gold states, update indices and hidden explanations are supplied only to trusted evaluation and the explicitly identified judging stage. Reader policy identifiers are not in prompts. The judge sees the benchmark rubric, gold context and three responses without policy or reader-model labels. This is blinded with respect to the compared selector, not human adjudication.","Raw model drafts are retained alongside explicit supervisor edits. The supervisor corrected a draft that confused high recency with a pure recent window, a draft that described candidate-turn change markers as query-derived, and an unsupported assertion about what prior work did not isolate. This separation makes the research process auditable instead of treating fluent model prose as evidence."]})
    references=[{"id":"stale","short":"Chao et al.(2026)","text":"Hanxiang Chao, Yihan Bai, Rui Sheng, Tianle Li, and Yushi Sun. STALE: Can LLM Agents Know When Their Memories Are No Longer Valid? arXiv:2605.06527v1, 2026.","url":"https://arxiv.org/abs/2605.06527"},
        {"id":"tangle","short":"Yang et al.(2026)","text":"Lu Yang, Shusheng Xu, Zhuoran Li, Tongkai Yang, and Longbo Huang. When Personal Memory Has No Single Answer: Evaluating LLM Agents under Irreducible Conflict. arXiv:2608.13921v1, 2026.","url":"https://arxiv.org/abs/2608.13921"},
        {"id":"trace","short":"Xiong et al.(2026)","text":"Wenjun Xiong et al. TRACE: Governing Memory Validity in Evolving Multi-Agent Systems. arXiv:2609.33517v1, 2026.","url":"https://arxiv.org/abs/2609.33517"},
        {"id":"bm25","short":"Robertson and Zaragoza(2009)","text":"Stephen Robertson and Hugo Zaragoza. The Probabilistic Relevance Framework: BM25 and Beyond. Foundations and Trends in Information Retrieval, 3(4):333-389, 2009.","url":"https://doi.org/10.1561/1500000019"},
        {"id":"longmemeval","short":"Wu et al.(2025)","text":"Di Wu et al. LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory. ICLR, 2025.","url":"https://arxiv.org/abs/2410.10813"}]
    abstract="Query-relevant memories need not contain the evidence that makes an older fact invalid. We audit this distinction using raw-user-turn retrieval on the public STALE benchmark. A scenario-level split reserves 80 cases for two bounded, model-proposed development iterations and 320 for frozen evaluation. At a 4096-byte context ceiling, the retained temporal-and-change-cue selector improves normalized verbatim update inclusion over BM25 by {{C_primary}}. Its incremental gain over a fixed temporal baseline is {{C_incremental}}, leaving the contribution of the change cue unresolved. A stronger-recency candidate degrades containment in this STALE construction. A separate paired reader pilot tests whether retained evidence supports responses judged to respect the new state. "+("{{C_reader}} " if reader_path.exists() else "Reader outcomes are pending in this intermediate draft. ")+"The contribution is a reproducible availability and reader audit with supervised, evidence-bound research artifacts, not a new memory architecture or an official full-context benchmark score."
    doc={"title":"Update Evidence Under Tight Context Budgets: A Retrieval and Reader Audit on STALE","author":"Team Neng Gong Zhi Ren","abstract":abstract,"sections":sections,"references":references,"claims":claims,"evidence":evidence}
    write_json(BASE/"approved-sections.json",approved)
    write_json(BASE/"claims.json",claims)
    tex_binary=os.environ.get("RESEARCH_LAB_TEX_BINARY") or shutil.which("pdflatex") or "pdflatex"
    output=compile_document(doc,Path(output_dir) if output_dir else ROOT/"paper/v4",tex_binary=tex_binary)
    print("Compiled",str(output),"sha256",digest(output))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output", help="override PDF/document output directory")
    args=parser.parse_args()
    build(args.output)
