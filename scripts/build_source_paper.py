"""Build evidence-bound ICLR manuscript source and figures; no model calls."""
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import read_json,write_text,write_json,digest
from research_lab.report import tex_escape


def build():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    analysis=read_json(ROOT/'research/memory_v3/results/analysis.json')
    pilot=read_json(ROOT/'outputs/source-reader-pilot/summary.json')
    resource=read_json(ROOT/'outputs/source-reader-pilot/resource_report.json')
    output=ROOT/'paper';output.mkdir(exist_ok=True)
    for p in (ROOT/'references/templates/iclr2026').glob('*.sty'): shutil.copyfile(p,output/p.name)
    shutil.copyfile(ROOT/'references/templates/iclr2026/iclr2026_conference.bst',output/'iclr2026_conference.bst')
    names={'event_window':'Event window','latest':'Source-blind latest','source':'Source LRU','no_revoke':'No revocation',
           'no_version':'No version check','gated':'Coverage gate','protected':'Protected gate'}
    lookup={(r['split'],r['budget'],r['policy']):r for r in analysis['summary']}
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,axes=plt.subplots(2,2,figsize=(7.2,4.6),sharex=True)
    for col,split in enumerate(('holdout','stress')):
      for policy,color,mark in [('event_window','#8293a9','s'),('source','#2576b8','o'),('gated','#d09224','^'),('protected','#20816b','D')]:
        for row,metric in enumerate(('accuracy','stale_rate')):
          axes[row,col].plot([384,768,1536],[lookup[split,b,policy][metric] for b in (384,768,1536)],label=names[policy],color=color,marker=mark,markersize=4)
      axes[0,col].set_title('Standard held-out' if split=='holdout' else 'Stress shift')
      for row in (0,1):
        axes[row,col].grid(alpha=.2);axes[row,col].set_ylim(-.025,1.025 if row==0 else .21)
        axes[row,col].set_xticks([384,768,1536]);axes[row,col].set_xlabel('Retained-state budget (bytes)')
    axes[0,0].set_ylabel('Exact accuracy');axes[1,0].set_ylabel('Stale-answer rate')
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=4,frameon=False)
    fig.tight_layout(rect=[0,.07,1,1]);fig.savefig(output/'budget_curves.png',dpi=230);plt.close(fig)
    def pct(x): return f'{100*x:.2f}'
    table=[]
    for policy in names:
      r=lookup['holdout',384,policy];s=lookup['stress',384,policy]
      table.append(f"{names[policy]} & {pct(r['accuracy'])} & {pct(r['stale_rate'])} & {pct(r['abstain_rate'])} & {pct(s['accuracy'])} & {pct(s['stale_rate'])} \\")
    reader=[]
    for r in pilot['methods']:
      alias,policy=r['method'].split('_',1)
      reader.append(f"{alias.capitalize()} & {names[policy]} & {round(r['mean']*12)}/12 & {r['errors']} \\")
    full=[]
    for r in analysis['summary']:
      if r['split']=='dev':
        continue
      full.append(f"{'Std.' if r['split']=='holdout' else 'Stress'} & {r['budget']} & {names[r['policy']]} & {pct(r['accuracy'])} & {pct(r['stale_rate'])} & {pct(r['abstain_rate'])} & {pct(r['false_concrete_conflict_rate'])} \\")
    pairs=[]
    for r in analysis['paired']:
      if r['budget']==384 and r['metric'] in ('accuracy','stale_rate'):
        pairs.append(f"{'Std.' if r['split']=='holdout' else 'Stress'} & {names[r['treatment']]} vs. {names[r['control']]} & {r['metric'].replace('_',' ')} & {100*r['delta']:+.2f} & [{100*r['ci95'][0]:+.2f}, {100*r['ci95'][1]:+.2f}] \\")
    # TeX table rows require two literal backslashes.
    table,reader,full,pairs=([line.rstrip(chr(92)) + chr(92)*2 for line in rows] for rows in (table,reader,full,pairs))
    discussion_path=ROOT/'outputs/deepseek-source-discussion-001/proposal.json'
    discussion=read_json(discussion_path)['summary'] if discussion_path.exists() else ''
    if discussion:
        # Use the checked opening excerpt; remaining limitations are stated above.
        discussion='. '.join(discussion.split('. ')[:2]).rstrip('.')+'.'
    manuscript=r'''\documentclass{article}
\usepackage{iclr2026_conference,times}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{graphicx,booktabs,longtable,amsmath,amssymb,hyperref,url}
\title{Source Coverage and Revocation\\in Byte-Bounded Agent Memory}
\author{Team Neng Gong Zhi Ren}
\iclrfinalcopy
\begin{document}
\maketitle
\lhead{CCF BDCI 2026 competition manuscript; not an ICLR submission}
\begin{abstract}
Agent memory must handle facts that change, are revoked, or disagree across
sources. Under a storage limit, preserving a value can be easier than preserving
the evidence required to use it. We study this distinction with a controlled
event-stream benchmark and seven deterministic policies at three exact serialized-
byte ceilings. The evaluation includes 1,200 held-out queries and 1,200 stress
queries, paired across all policies and budgets. At 384 bytes, requiring both
source slots removes concrete answers to live conflicts in our standard suite,
but increases abstention and reduces exact accuracy by 0.92 percentage points;
it does not reduce the already-zero stale-answer rate of source-aware LRU.
Prioritizing revocation records recovers 3.17 points of accuracy relative to this
gate. Under stress, however, complete source coverage can still contain stale
replayed values after version watermarks are evicted. A 72-call, two-model reader
pilot further separates retention errors from reading and truncation errors.
These results support explicit coverage and version diagnostics, not a general
correctness guarantee. We release the frozen protocol, executable generators,
per-query outputs and a supervised research workflow using modified JiuwenSwarm
artifact verification.
\end{abstract}

\section{Introduction}
A long-lived assistant cannot safely treat every remembered statement as current.
For example, one source may retract an inventory status while another source
still supports a different status. Returning the newest-looking value collapses
two questions: which values remain valid, and whether all relevant source states
are still represented. A finite memory may lose either the value or the metadata
that makes the value interpretable. This motivates a narrow question: what happens
when source coverage and invalidation state compete with content for the same
byte budget?

Our study isolates this question rather than proposing a new general-purpose
memory architecture. All incoming events have explicit, machine-readable
source and version identifiers; extraction from dialogue is outside scope.
The main comparisons hold representation and source-aware reduction constant:
source LRU versus a two-source coverage gate, then ordinary eviction versus
tombstone-prioritized eviction. We also include a recent-event window and weaker
diagnostics that omit sources, revocation, or version checks. The design makes
the cost of metadata and conservative answering visible.

The findings are mixed. The gate addresses one-sided answers to conflicts but
does not improve the primary stale-answer metric over source LRU in the tested
standard setting. Tombstone priority has budget-dependent gains and a small observed
accuracy decrease in the largest stress-budget cell. More fundamentally, neither
two retained slots nor retained revocations certify that a version watermark
survived earlier eviction. We show a concrete replay counterexample and preserve
all unfavorable results. This is a synthetic mechanism study and an auditable
semi-automated research artifact, not a claim of state-of-the-art agent ability.

\section{Related work and scope}
LongMemEval evaluates long-term interactive memory through information extraction,
multi-session and temporal reasoning, knowledge updates, and abstention
\citep{wu2025longmemeval}. It motivates measuring more than answer recall, but we
do not use its dataset or compare our synthetic scores to its results.
A-MEM dynamically links structured notes and evolves memory attributes
\citep{xu2025amem}; Mem0 extracts and updates salient memories, including a graph
extension \citep{chhikara2025mem0}. These systems already address evolving memory,
so source fields and update operations alone are not our novelty claim.
RECON explicitly considers source conflict and cascading invalidation over long
narratives \citep{arya2026recon}. Our flat, two-source event semantics are much
simpler and do not test compositional dependency propagation. The contribution
here is a controlled byte-accounted comparison, explicit failure witnesses, and
the provenance of a supervised experimental workflow. None of the simple
policies below should be interpreted as a faithful reproduction of these systems.

\section{Task and byte-bounded policies}
\subsection{Public semantics and independent oracle}
Each event is a put $P(k,s,v,x)$ or revoke $R(k,s,v)$ for key $k$, declared source
$s\in\{a,b\}$ and positive integer version $v$. Version numbers are local to
$(k,s)$ and incomparable across sources. Sources have equal authority. The
highest observed version for a source is current; an explicit revoke at that
version cancels it permanently, including if its put arrives later as a replay.
An older version does not revive. Let $V_k$ be the set of remaining active values
across the two sources. The target is the sole value if $|V_k|=1$,
\texttt{CONFLICT} if $|V_k|>1$, and \texttt{UNKNOWN} otherwise.
\texttt{ABSTAIN} is a separate prediction for insufficient retained evidence and
is not automatically credited on unknown targets.

The reference oracle computes the target in batch from the complete history by
filtering each source and finding its maximum version. Policies instead consume
one event at a time and receive the query only after all writes. They cannot read
the family label, oracle, generator seed, or previous evicted entries. This
separates evaluator access from predictor information. Hand-derived fixtures
check updates, conflict, selective and total revocation, replay, and
revoke-before-put order; a separate collision fixture documents the weak
source-blind policy's incorrect behavior.

\subsection{Representations, eviction, and comparisons}
The persistent state of every policy is exactly its compact JSON list. UTF-8
bytes include brackets, commas, keys, source names, version integers and values.
For each event, the policy updates its state then evicts until serialized size
is at most $B\in\{384,768,1536\}$. This is a retained-state bound; it does not
bound transient ingestion memory, Python object overhead, or model tokens.
No separate index, remembered evicted-key set, or hidden version map is free.

\textbf{Event window} retains the largest arrival suffix fitting the budget as
five-field event records and reconstructs state from that suffix at read time.
\textbf{Source LRU} stores four-field slots $[k,s,v,x]$, with JSON null for
revoked state. It rejects lower versions and replay of a tombstoned version,
moves accepted updates to the end, and evicts oldest slots. \textbf{No revocation}
ignores revoke events; \textbf{No version check} permits arriving puts to overwrite
newer versions. These are mechanism diagnostics, not competitive full systems.
\textbf{Source-blind latest} collapses the source to a constant, overwrites on
put, and clears on revokes whose number is at least the retained number. Its
cross-source mistakes are intentional and are not the basis for the main claims.

\textbf{Coverage gate} uses exactly source LRU's retained state but returns
\texttt{ABSTAIN} unless both source slots are present. \textbf{Protected gate}
adds the same gate and evicts the oldest positive slot before a null tombstone;
if all slots are tombstones, it evicts the oldest one. Both still pay for complete
slot metadata. Source LRU interprets retained slots without assuming missing
sources are present; this can produce a concrete answer when a lost source would
have made the full-history answer a conflict. The gate addresses that coverage
problem, at the cost of rejecting some otherwise-correct singleton answers.

\section{Frozen experimental protocol}
\subsection{Synthetic data and separation}
Each seed produces 120 end-of-stream queries, 20 each for steady values, updates,
total revocation, conflict, conflict resolution, and replay. Every key initially
has matching values from both sources. Standard streams contain 12 keys, 64
background events, and a query-specific transition with lag drawn from
$\{0,4,12,36\}$ events. Background events exclude the eventual query key, creating
controlled rather than naturalistic memory pressure. The query key itself is
randomized and unavailable to the policy during writes.

Development uses three seeds. Ten distinct seeds define the standard held-out
set, and ten others define the stress set. Stress doubles the keys and background
events, lengthens key/value strings, and places distracting events between new
versions and old replays. These simultaneous changes make it an aggregate stress
test; they do not isolate each distribution factor or constitute independent
real-world transfer. The protocol, code, tests and plans were hashed after
development and before holdout. We did not tune or choose a policy using held-out
scores. All seven policies and three budgets were retained: 483 CPU jobs including
63 development jobs, or 57,960 paired predictions, not 57,960 independent tasks.

\subsection{Metrics and uncertainty}
The preregistered primary metric is stale-answer rate over \emph{all} queries:
a concrete prediction appeared historically for the query key but is absent from
the oracle's active value set. A value belonging to one side of a currently live
conflict is a wrong concrete answer, but is not stale by this definition. We
therefore also report the conditional false-concrete rate on conflict targets,
exact accuracy, abstention, singleton-target recall, and unknown/conflict
accuracy. An always-abstain policy would have zero stale rate and zero exact
accuracy, demonstrating why stale rate alone is insufficient.

Results average equally over seeds, each containing equal numbers of queries.
Paired differences use the same seeds and traces for each method. Descriptive
95\% percentile bootstrap intervals resample the ten seeds with replacement for
10,000 draws, using analysis seed 20260929. We make no multiple-comparison-adjusted
significance claim. The full per-seed and per-family tables permit alternative
analyses without rerunning model calls.

\section{Results}
\begin{table}[t]
\centering\small
\begin{tabular}{lrrrrr}\toprule
&\multicolumn{3}{c}{Standard, 384 bytes}&\multicolumn{2}{c}{Stress, 384 bytes}\\
Policy & Acc. & Stale & Abstain & Acc. & Stale\\\midrule
@@MAIN_TABLE@@
\bottomrule\end{tabular}
\caption{Percentages over 1,200 paired queries per split. The low primary error
of a policy can coexist with low accuracy. Source-blind latest is a weak
diagnostic, not the main source-aware baseline.}\label{tab:main}
\end{table}

\subsection{Coverage gates suppress one-sided conflict answers, not stale replay}
At 384 bytes in the standard suite, source LRU returns concrete values on
72.50\% of conflict targets. The coverage gate reduces this to 0\%, while
abstention rises from 36.75\% to 62.25\%. Exact accuracy falls from 38.67\% to
37.75\%, a paired difference of $-0.92$ percentage points (95\% interval
$[-1.33,-0.50]$). The primary stale rate is zero for both. Thus gating's measured
benefit here is conflict caution; we cannot claim it reduced staleness relative
to source LRU. At 768 and 1,536 bytes, source LRU and both gates reach 100\%
standard accuracy. This saturation reflects simple structured semantics and
sufficient capacity, not broad agent competence.

\subsection{Tombstone priority offers conditional gains}
Protected gate improves standard 384-byte accuracy over ordinary gating by
3.17 points (95\% interval $[2.17,4.00]$), from 37.75\% to 40.92\%. In 384-byte
stress, accuracy rises from 16.42\% to 20.50\% and stale rate falls from 16.67\%
to 12.83\%; the paired stale difference is $-3.83$ points
($[-4.92,-2.75]$). This is not uniformly successful: at 1,536 stress bytes,
protected accuracy is 32.83\%, versus 33.25\% with ordinary gating, while both
still have 16.67\% stale rate. The isolated accuracy difference is $-0.42$ points
(descriptive 95\% interval $[-0.75,-0.08]$); this is not evidence of a monotonic
scaling trend or a multiple-comparison-adjusted conclusion. Protecting negative records can crowd out useful
positive state. All three budget points and unfavorable changes appear in
Figure~\ref{fig:curves} and Appendix~\ref{app:all}.

\begin{figure}[t]\centering
\includegraphics[width=\linewidth]{budget_curves.png}
\caption{The same serialized-byte ceiling does not imply the same retained
information. Standard accuracy saturates for source-aware state; stress replay
errors persist even with a coverage gate. Lines connect three tested budgets
and do not imply performance at intermediate budgets.}\label{fig:curves}
\end{figure}

\subsection{A concrete failure witness}
Let both sources assert $A$ at version 1, then $B$ at version 2. Enough unrelated
events evict those version-2 slots. Replay version-1 puts from both sources.
Protected gate may now retain two complete-looking slots for $A$, despite the
full-history target remaining $B$. The unit test constructs this witness and
asserts the stale answer. It is a failure of the tested bounded representation,
not an impossibility theorem for every memory algorithm. A bounded-horizon replay
assumption, authoritative freshness check, or budgeted persistent high-water mark
could address it, but none is present here. We do not silently give these methods
an unmetered history to eliminate the failure.

\section{Model-reader pilot}
The first 12 traces of held-out seed 101 (two per family, fixed in advance) are
read by the configured DeepSeek and Kimi routes from event-window, source-LRU,
and protected memories at 768 bytes. This produces 72 planned calls. Each reader
sees the query, retained state and its public representation semantics, not the
oracle, family, deterministic answer or full stream. Policy-specific instructions
explain the protected gate; therefore this pilot measures a memory-plus-reader
configuration, not a prompt-controlled comparison of models.

The output limit is 1,800 tokens and each task allows one attempt; truncated or
invalid answers count incorrect, with no selective retry. Model identities are
the gateway-reported aliases \texttt{deepseek-v4.1-flash} and \texttt{kimi-k3}, not
independently verified weights. Sampling defaults are server-defined, so exact
regeneration is not assured. Stored responses support replay of the scoring.

\begin{table}[h]\centering\small
\begin{tabular}{llrr}\toprule
Reader route & Memory & Correct & Invalid/truncated\\\midrule
@@READER_TABLE@@
\bottomrule\end{tabular}
\caption{Small reader pilot: 12 paired synthetic queries per row. Counts are not
a statistical ranking of model capability.}\label{tab:reader}
\end{table}
Both readers score 4/12 with event-window memory. Source and protected memory
yield 10/12 for DeepSeek and 12/12 for Kimi. Two DeepSeek source responses reach
the generation limit and count incorrect; its two protected errors are valid
outputs with incorrect answers. No reader produces a stale concrete value in
this small standard slice. API-reported pilot usage totals @@PILOT_TOKENS@@
tokens; reasoning tokens are included in output usage, not added twice. This
supports the feasibility of reading the representation, while leaving extraction,
longer tasks, stress-model behavior and reliability open.

\section{Research workflow and limitations}
The submitted system separates a supervisor, scoped model workers, deterministic
execution, integrity checking and report construction. Codex fixes the question,
checks literature, authors trusted implementation and accepts or rejects model
suggestions. DeepSeek proposed cases and a discussion paragraph; Kimi audited
the protocol. The supervisor rejected a model-proposed cross-source last-writer
rule and clarified local version scope after the audit. This is supervised
research, not an unattended discovery claim. The project directly imports the
modified JiuwenSwarm artifact-manifest module for hashes and verification. The
existing campaign engine also uses the added JiuwenSwarm budget module; the
present fixed grid uses the experiment pipeline. We do not claim to have run the
full SwarmFlow service.

The 483 CPU jobs consume @@CPU_SECONDS@@ aggregate process-wall seconds, which
is not the parallel launch's elapsed time. Actual API requests use a shared,
locked ledger with admission reservations. Failed calls without usage retain
unknown reservations; they are not reported as free. The resource report
distinguishes this study, historical connectivity attempts and total account
usage visible to this project. Codex-side service tokens and monetary pricing
are not available to the local ledger and are not claimed to be included.

Limitations are substantial. The generator, oracle and methods are designed
together under simple rules, so no language-understanding, real task, or
independent benchmark claim follows. The two sources are declared and equally
authoritative; identities, extraction, trust, incomplete source discovery,
dependency graphs and privacy deletion are not tested. Bytes are a reproducible
storage proxy, not model tokens or total machine RAM. Stress combines several
changes rather than isolating each. Confidence intervals quantify seed variation
under this generator and do not establish population-wide reliability. The pilot
is small, uses one model sample per cell and only the standard distribution.
Finally, a low stale rate can reward silence or incomplete conflict handling;
we explicitly retain accuracy and coverage guardrails.

\paragraph{Model-assisted discussion, checked by the supervisor.}
@@DISCUSSION@@

\section{Conclusion}
Under explicit byte accounting, retaining values, source coverage and revoked
state are competing objectives. A completeness gate reduces one-sided conflict
answers in this controlled study, but does not by itself reduce stale replay.
Protecting tombstones can recover accuracy and sometimes reduce stale answers,
yet also yields a negative result at larger stress capacity. The practical lesson
is to report invalidation, coverage and abstention separately, and to test what
happens after metadata is evicted. Our release makes these boundaries executable
and exposes the model-assisted research decisions that produced the paper.

\bibliography{references}
\bibliographystyle{iclr2026_conference}

\appendix
\section{Complete fixed-grid results}\label{app:all}
All entries below are percentages over 1,200 queries per split, paired across
methods and budgets. FC is the false-concrete rate conditioned on conflict targets
(200 queries per split). Machine-readable artifacts also report singleton recall,
UNKNOWN accuracy, per-family results and mean retained bytes. Development data
are archived but excluded from this table.
\small
\begin{longtable}{rrlrrrr}
\toprule Split & Bytes & Policy & Acc. & Stale & Abstain & FC\\\midrule\endhead
@@FULL_TABLE@@
\bottomrule
\end{longtable}
\normalsize
\section{Selected paired intervals}
Values are percentage-point differences at 384 bytes. Positive accuracy is
better; negative stale rate is better. These are descriptive seed-bootstrap
intervals, not multiplicity-adjusted hypothesis tests.
\begin{center}\scriptsize
\begin{tabular}{llrrl}\toprule
Split & Comparison & Metric & Delta & 95\% interval\\\midrule
@@PAIRS@@
\bottomrule\end{tabular}\end{center}

\section{Reproduction and evidence map}
The release contains \texttt{experiments/source\_memory/experiment.py}, the frozen
protocol and nine plans; \texttt{scripts/run\_source\_grids.py} executes the grids
through the research engine. \texttt{scripts/analyze\_source\_study.py} recomputes
tables from raw predictions. \texttt{scripts/source\_reader\_pilot.py} is the
explicit paid-call entry; replay its archived responses for offline checking.
\texttt{scripts/build\_source\_paper.py} constructs this manuscript and figure
from the verified results. Each CPU job archives its command, Python/platform
identity, stdout/stderr, input fingerprint, result and hash manifest. The freeze
timestamp and digests precede held-out execution. The release auditor replays
the archived implementation in a fresh process and compares its predictions
against all stored deterministic results; it is not an independent implementation.

\paragraph{Integrity boundary.}
SHA-256 manifests support artifact replay, not scientific novelty or benchmark
representativeness. Hand-derived semantic fixtures and the explicit replay
counterexample are executable in \texttt{tests/test\_source\_memory.py}.
\end{document}
'''
    replacements={'@@MAIN_TABLE@@':'\n'.join(table),'@@READER_TABLE@@':'\n'.join(reader),
        '@@FULL_TABLE@@':'\n'.join(full),'@@PAIRS@@':'\n'.join(pairs),
        '@@PILOT_TOKENS@@':f"{resource['reported_tokens']:,}",'@@CPU_SECONDS@@':f"{analysis['cpu_job_wall_seconds_sum']:.2f}",
        '@@DISCUSSION@@':tex_escape(discussion) if discussion else 'The discussion is based on the fixed quantitative analysis above.'}
    for key,value in replacements.items(): manuscript=manuscript.replace(key,value)
    write_text(output/'paper.tex',manuscript)
    write_text(output/'references.bib',r'''@inproceedings{wu2025longmemeval,
 title={LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory},
 author={Wu, Di and Wang, Hongwei and Yu, Wenhao and Zhang, Yuwei and Chang, Kai-Wei and Yu, Dong},
 booktitle={International Conference on Learning Representations},year={2025},url={https://arxiv.org/abs/2410.10813}}
@inproceedings{xu2025amem,title={A-MEM: Agentic Memory for LLM Agents},author={Xu, Wujiang and Liang, Zujie and Mei, Kai and Gao, Hang and Tan, Juntao and Zhang, Yongfeng},booktitle={Advances in Neural Information Processing Systems},year={2025},url={https://arxiv.org/abs/2502.12110}}
@misc{chhikara2025mem0,title={Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory},author={Chhikara, Prateek and Khant, Dev and Aryan, Saket and Singh, Taranjeet and Yadav, Deshraj},year={2025},howpublished={arXiv:2504.19413},url={https://arxiv.org/abs/2504.19413}}
@misc{arya2026recon,title={RECON: Benchmarking Agent Memory for Compositional Reasoning over Long Contexts},author={Arya, Mihir Shriniwas},year={2026},howpublished={arXiv:2607.16716},url={https://arxiv.org/abs/2607.16716}}
''')
    write_json(output/'build_sources.json',{'analysis_sha256':digest(ROOT/'research/memory_v3/results/analysis.json'),
        'pilot_summary_sha256':digest(ROOT/'outputs/source-reader-pilot/summary.json'),
        'discussion_sha256':digest(discussion_path) if discussion_path.exists() else None,
        'template_source':'https://github.com/ICLR/Master-Template/tree/master/iclr2026'})
    print('Manuscript and figures written to paper/.')


if __name__=='__main__': build()
