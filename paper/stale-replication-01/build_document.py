"""Build an evidence-bound STALE report without rerunning experiments or models."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from research_lab.manuscript import compile_document
from research_lab.storage import digest, read_json, write_json

PROJECT = ROOT / "projects/alice-stale-replication-01"
OUTPUT = Path(__file__).resolve().parent
LABELS = {
    "turn_bm25": "Turn BM25", "turn_timecue": "Turn + time/cue",
    "turn_rrf": "Turn RRF", "turn_density": "Turn density", "turn_stop": "Turn stop",
    "sentence_bm25": "Sentence BM25", "sentence_timecue": "Sentence + time/cue",
    "sentence_rrf": "Sentence RRF", "sentence_density": "Sentence density",
}


def artifact(stage, filename):
    result = read_json(PROJECT / "artifacts" / stage / "1" / "result.json")
    entry = next(item for item in result["artifacts"] if Path(item["path"]).name == filename)
    path = (PROJECT / entry["path"]).resolve()
    if not path.is_relative_to(PROJECT.resolve()) or digest(path) != entry["sha256"]:
        raise ValueError("Project artifact changed: " + filename)
    return path


def percent(value):
    return "N/A" if value is None else f"{100 * value:.2f}"


def estimate(row):
    if row["mean"] is None:
        return "not estimated (no scheduled observations)"
    return (f"{100 * row['mean']:+.2f} percentage points "
            f"(95% bootstrap interval {100 * row['ci95'][0]:+.2f} to "
            f"{100 * row['ci95'][1]:+.2f}; n={row['n']})")


def table(caption, headers, rows):
    return {"caption": caption, "headers": headers, "rows": rows}


def figures(retrieval):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    directory = PROJECT / "derived-figures"
    directory.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    indexed = {(row["method"], row["budget"]): row for row in retrieval["summary"]}
    methods = list(LABELS)
    budgets = sorted({row["budget"] for row in retrieval["summary"]})
    saved = {}

    def save(name, figure):
        figure.tight_layout()
        path = directory / ("stale_" + name + ".png")
        figure.savefig(path, dpi=220, bbox_inches="tight")
        plt.close(figure)
        saved[name] = str(path)

    figure, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    positions = np.arange(len(methods))
    for axis, metric, title in zip(axes, ("new", "old"), ("New-state inclusion", "Old-state inclusion")):
        values = [indexed[method, 4096][metric] for method in methods]
        means = np.array([100 * item["mean"] for item in values])
        errors = np.array([[means[index] - 100 * item["ci95"][0],
                            100 * item["ci95"][1] - means[index]]
                           for index, item in enumerate(values)]).T
        axis.barh(positions, means, xerr=errors, capsize=2,
                  color=["#247b83" if method.startswith("turn") else "#bd7448" for method in methods])
        axis.set_yticks(positions, [LABELS[method] for method in methods])
        axis.invert_yaxis()
        axis.set_title(title + " at 4096 bytes")
        axis.set_xlabel("Scenario-averaged inclusion (%)")
        axis.grid(axis="x", alpha=.2)
    save("retrieval", figure)

    figure, axes = plt.subplots(1, 2, figsize=(9, 3.3))
    for method in ("turn_bm25", "sentence_bm25", "turn_timecue", "sentence_timecue"):
        values = [indexed[method, budget]["new"] for budget in budgets]
        means = np.array([100 * item["mean"] for item in values])
        axes[0].plot(budgets, means, marker="o", label=LABELS[method])
        axes[0].fill_between(budgets, [100 * item["ci95"][0] for item in values],
                             [100 * item["ci95"][1] for item in values], alpha=.08)
    axes[0].set_xscale("log", base=2)
    axes[0].set_xticks(budgets, [str(budget) for budget in budgets])
    axes[0].set_xlabel("History budget (UTF-8 bytes)")
    axes[0].set_ylabel("New-state inclusion (%)")
    axes[0].legend(fontsize=7)
    paired = [next(row for row in retrieval["paired"]
                   if row["method"] == "sentence_bm25" and row["budget"] == budget) for budget in budgets]
    means = np.array([100 * row["mean"] for row in paired])
    errors = np.array([[means[index] - 100 * row["ci95"][0], 100 * row["ci95"][1] - means[index]]
                       for index, row in enumerate(paired)]).T
    axes[1].errorbar(range(len(budgets)), means, yerr=errors, marker="o", capsize=4)
    axes[1].axhline(0, color="black", linewidth=.8)
    axes[1].set_xticks(range(len(budgets)), [str(budget) for budget in budgets])
    axes[1].set_xlabel("History budget (UTF-8 bytes)")
    axes[1].set_ylabel("Sentence minus turn BM25 (pp)")
    for axis in axes:
        axis.grid(alpha=.2)
    save("budget_comparison", figure)

    figure, axis = plt.subplots(figsize=(7.5, 2.8))
    states = ("neither", "old_only", "new_only", "both")
    left = np.zeros(len(methods))
    for state, color in zip(states, ("#d9dde1", "#a6b9d0", "#5fac9e", "#247b83")):
        values = [100 * next(row for row in retrieval["joint"]
                            if row["method"] == method and row["budget"] == 4096
                            and row["state"] == state)["mean"] for method in methods]
        axis.barh(positions, values, left=left, label=state.replace("_", " "), color=color)
        left += values
    axis.set_yticks(positions, [LABELS[method] for method in methods])
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.set_xlabel("Scenario-averaged query share (%)")
    axis.legend(ncol=4, loc="upper center", bbox_to_anchor=(.5, 1.2), fontsize=8)
    save("joint_states", figure)

    figure, axes = plt.subplots(1, 2, figsize=(9, 3))
    alphas = sorted({row["alpha"] for row in retrieval["sensitivity"]})
    betas = sorted({row["beta"] for row in retrieval["sensitivity"]})
    matrix = [[100 * next(row for row in retrieval["sensitivity"]
                         if row["alpha"] == alpha and row["beta"] == beta)["mean"]
               for beta in betas] for alpha in alphas]
    axes[0].imshow(matrix, cmap="YlGnBu", aspect="auto")
    for row_index, values in enumerate(matrix):
        for column_index, value in enumerate(values):
            axes[0].text(column_index, row_index, f"{value:.1f}", ha="center", va="center",
                         color="white" if value > 30 else "black")
    axes[0].set_xticks(range(len(betas)), [str(beta) for beta in betas])
    axes[0].set_yticks(range(len(alphas)), [str(alpha) for alpha in alphas])
    axes[0].set_xlabel("Change-cue weight beta")
    axes[0].set_ylabel("Recency weight alpha")
    axes[0].set_title("Turn inclusion (%) at 4096 bytes")
    strata = retrieval["strata"]
    for index, row in enumerate(strata):
        axes[1].errorbar(100 * row["mean"], index,
                         xerr=[[100 * (row["mean"] - row["ci95"][0])],
                               [100 * (row["ci95"][1] - row["mean"])]], fmt="o", capsize=3)
    axes[1].set_yticks(range(len(strata)),
                       [row["field"].replace("_", " ") + ": " + row["side"] for row in strata], fontsize=8)
    axes[1].invert_yaxis()
    axes[1].axvline(0, color="black", linewidth=.8)
    axes[1].set_xlabel("Sentence minus turn BM25 (pp)")
    axes[1].set_title("Descriptive median-split strata")
    save("sensitivity_strata", figure)
    return saved


def build():
    retrieval_path = artifact("retrieval", "retrieval-summary.json")
    reader_path = artifact("analysis", "reader-analysis.json")
    draft_path = artifact("manuscript", "paper_draft.md")
    retrieval = read_json(retrieval_path)
    reader = read_json(reader_path)
    freeze_path = PROJECT / "artifacts/freeze/1/result.json"
    protocol = read_json(freeze_path)["values"]["protocol"]
    for filename, expected in protocol["source_hashes"].items():
        if digest(ROOT / filename) != expected:
            raise ValueError("Frozen method source changed: " + filename)
    indexed = {(row["method"], row["budget"]): row for row in retrieval["summary"]}
    budgets = sorted({row["budget"] for row in retrieval["summary"]})
    primary = next(row for row in retrieval["paired"]
                   if row["method"] == "sentence_bm25" and row["budget"] == 4096)
    reader_pairs = [row for row in reader["paired"] if row["treatment"] == "sentence_bm25"]
    evidence_paths = {
        "retrieval": retrieval_path, "reader": reader_path, "protocol": freeze_path,
        "draft": draft_path, "packing_source": ROOT / "src/research_lab/stale_packing_v5.py",
        "lexical_source": ROOT / "src/research_lab/stale_retrieval.py",
    }
    claims = []

    def claim(identifier, text, evidence_ids):
        claims.append({"id": identifier, "text": text, "evidence_ids": evidence_ids})
        return "{{" + identifier + "}}"

    primary_text = claim("C_primary", estimate(primary), ["retrieval"])
    scope_text = claim("C_scope",
        f"The retrieval evaluation contains {retrieval['n_scenarios']} scenarios and "
        f"{retrieval['retrieval_rows']:,} query-method-budget records, covering "
        f"{len(LABELS)} methods and {len(budgets)} history budgets.",
        ["retrieval", "packing_source"])
    reader_text = claim("C_reader",
        f"The reader pilot includes {len(protocol['reader_uids'])} scenarios, "
        f"{reader['attempted']} attempted answers, {reader['answered']} valid answers and "
        f"{reader['graded']} model-graded answers.", ["reader", "protocol"])
    arm_text = claim("C_arms",
        "At the primary budget, turn BM25 includes the new statement at "
        f"{percent(indexed['turn_bm25', 4096]['new']['mean'])}% and sentence BM25 at "
        f"{percent(indexed['sentence_bm25', 4096]['new']['mean'])}%. "
        "Their update-session coverage is respectively "
        f"{percent(indexed['turn_bm25', 4096]['update_session']['mean'])}% and "
        f"{percent(indexed['sentence_bm25', 4096]['update_session']['mean'])}%.", ["retrieval"])
    ceiling = retrieval["ceiling"]
    ceiling_text = claim("C_ceiling",
        f"The full user-turn pool contains a normalized exact new-state match in "
        f"{ceiling['user_exact']}/{retrieval['n_scenarios']} scenarios and a contiguous-token match in "
        f"{ceiling['user_token']}/{retrieval['n_scenarios']}. Assistant exact matches occur in "
        f"{ceiling['assistant_exact']} scenarios, with {ceiling['assistant_only']} assistant-only exact matches.",
        ["retrieval"])
    diagnostic_text = claim("C_diagnostic",
        f"At 4096 bytes, turn RRF old-state inclusion is "
        f"{percent(indexed['turn_rrf', 4096]['old']['mean'])}%. Turn stop uses an average of "
        f"{indexed['turn_stop', 4096]['bytes']['mean']:.1f} bytes, compared with "
        f"{indexed['turn_bm25', 4096]['bytes']['mean']:.1f} for turn BM25.",
        ["retrieval"])
    pairs_text = " ".join(claim("C_pair_" + row["model"],
        row["model"] + " has a paired sentence-minus-turn judged-pass contrast of " + estimate(row) + ".",
        ["reader"]) for row in reader_pairs)
    assets = figures(retrieval)
    for name, path in assets.items():
        evidence_paths["figure_" + name] = Path(path)

    def figure(name, caption):
        return {"path": assets[name], "caption": caption}

    primary_table = table(
        "Retrieval at 4096 UTF-8 history bytes. Inclusion values are scenario-averaged percentages; "
        "bytes are mean serialized history sizes. These are lexical availability diagnostics.",
        ["Method", "New", "Old", "Token new", "Session", "Bytes"],
        [[LABELS[method]] + [percent(indexed[method, 4096][metric]["mean"])
                           for metric in ("new", "old", "token_new", "update_session")]
         + [f"{indexed[method, 4096]['bytes']['mean']:.1f}"] for method in LABELS])
    reader_table = table(
        "Reader completion and judged passes. A/Ans/G/P denote attempted, answered, graded and passed. "
        "Intervals are the stored empirical bootstrap intervals, which are unstable for this small sample.",
        ["Model / arm", "A/Ans/G/P", "Pass (%)", "95% interval"],
        [[row["model"] + " / " + ("sentence" if row["arm"].startswith("sentence") else "turn"),
          "/".join(str(row[key]) for key in ("attempted", "answered", "graded", "passed")),
          percent(row["mean"]), f"{percent(row['ci95'][0])} to {percent(row['ci95'][1])}"]
         for row in reader["summary"]])
    paired_table = table(
        "Reader sentence-minus-turn contrasts in percentage points. Missing-data bounds assign each "
        "ungraded answer to failure or success over all scheduled pairs; they are not confidence intervals.",
        ["Model", "Pairs", "Delta", "95% interval", "Missing bounds"],
        [[row["model"], str(row["n"]), percent(row["mean"]),
          f"{percent(row['ci95'][0])} to {percent(row['ci95'][1])}",
          f"{percent(row['missing_bounds'][0])} to {percent(row['missing_bounds'][1])}"]
         for row in reader_pairs])

    sections = [
        {"heading": "Introduction", "paragraphs": [
            "A user can revise a preference, constraint or personal fact after stating an older version. "
            "Retrieval must then provide a reader with evidence of the revision rather than merely a passage "
            "that resembles the question. The STALE benchmark makes this distinction observable through "
            "conversations containing old and updated states [stale]. We examine a narrow part of this problem: "
            "whether smaller retrieval units improve access to the updated statement when history must fit "
            "within an explicit byte ceiling.",
            "Sentence retrieval is attractive because it can pack shorter passages into the same budget. "
            "However, splitting turns also changes document frequencies, average document length, ranking ties "
            "and serialization overhead. It may separate a statement from the surrounding text that makes it "
            "retrievable. The direction of the resulting effect cannot be assumed from unit size alone. "
            "We compare the actual implementations at equal serialized history ceilings.",
            scope_text + " The primary question is the sentence-BM25 minus turn-BM25 difference in new-state "
            "containment at 4096 bytes. We preserve the frozen contrast and report all secondary configurations "
            "without selecting a new winner after inspecting their outcomes.",
            "The primary paired contrast is " + primary_text + ". The negative direction motivates a distinction "
            "between reaching the update session and preserving the exact updated statement. A separate reader "
            "pilot asks whether the two contexts support actions consistent with the updated state.",
            "This is retrospective reuse of an exposed dataset. Freezing this run makes its choices traceable, "
            "but does not create an unseen test set. The contribution is a documented comparison of retrieval "
            "units, packing policies and lexical diagnostics, with a clearly bounded reader pilot."
        ]},
        {"heading": "Related Work and Evaluation Scope", "paragraphs": [
            "STALE asks whether agents recognize that their memories are no longer valid [stale]. Its old-state, "
            "new-state and probing-query annotations allow us to inspect what a byte-limited context contains. "
            "Our reader evaluation adapts only its implicit task-compliance dimension. We do not implement "
            "the original paper's complete memory system or compare these scores with full-context leaderboard results.",
            "BM25 is a sparse term-frequency and document-frequency retrieval model [bm25]. It provides an "
            "interpretable starting point for isolating implementation choices. Our sentence and turn indexes "
            "use the same tokenizer and BM25 constants, but their document collections differ. This comparison "
            "therefore measures the complete unit-and-index change, rather than a pure intervention on passage length.",
            "Recency, lexical change cues, reciprocal-rank fusion and score-per-byte ranking are fixed "
            "heuristics in this study. They provide diagnostic alternatives to the main comparison. Dense "
            "embedding retrieval, learned reranking, memory consolidation and semantic verification are outside "
            "the evaluated method set; the current evidence cannot establish superiority over those approaches."
        ]},
        {"heading": "Retrieval Units, Scoring and Packing", "paragraphs": [
            "Only user turns enter the retrieval index. Each whole-turn document retains its session and turn "
            "position. The sentence index splits the same text deterministically at punctuation followed by "
            "whitespace, or at newlines, and retains a sentence ordinal. This is a simple boundary rule rather "
            "than a linguistic sentence parser. Assistant content is excluded from ranking.",
            "Tokenization lowercases text, extracts ASCII alphanumeric tokens and removes the fixed stopword "
            "set in the pinned lexical source. BM25 uses k1=1.2 and b=0.75; query terms are deduplicated. "
            "The inverse-document-frequency term is log(1 + (N - df + 0.5)/(df + 0.5)). Each index computes "
            "its own document counts, lengths and average length. A query's BM25 scores are divided by their "
            "maximum, with a denominator of one if all scores are zero.",
            "The time/cue variant adds alpha times normalized user-turn position and beta times a binary "
            "change-marker indicator, with default alpha=0.25 and beta=0.1. All sentences within a turn "
            "share that turn's recency. The cue regex matches markers such as now, no longer, switched, "
            "changed, stopped and actually in the candidate text. It does not use the query or gold update label.",
            "RRF combines lexical and recency ranks as 1/(60 + lexical_rank) + 1/(60 + recency_rank), "
            "with one-based ranks. Density divides the normalized lexical score by serialized byte length. "
            "Higher document ordinals resolve ranking ties. The turn-stop variant uses BM25 but stops at "
            "the first passage that does not fit; other variants skip oversized passages and continue.",
            "Byte accounting includes the bracketed session/turn headers, sentence headers where applicable, "
            "text and newline characters in UTF-8. Selected passages are restored to index order before "
            "serialization. Gold states and relevant-session annotations are used for host-side scoring, "
            "not ranking. The ceiling applies to history only, not the full API prompt or its token count."
        ]},
        {"heading": "Protocol, Outcomes and Uncertainty", "paragraphs": [
            scope_text + " The budgets are " + ", ".join(str(budget) for budget in budgets) +
            " UTF-8 bytes. Each method-budget combination evaluates all three probing queries per scenario. "
            "The resulting rows share scenarios and should not be treated as independent observations.",
            "The primary new and old metrics test substring containment after NFKC normalization, whitespace "
            "collapse and case folding. They retain punctuation. The separate token-new metric compares contiguous "
            "word tokens after normalization and thus tolerates punctuation differences. Update-session coverage "
            "asks whether any selected document comes from the annotated last relevant session; it does not "
            "require that the updated statement itself was selected.",
            "The primary contrast is fixed in the project protocol: sentence BM25 minus turn BM25 at "
            "4096 history bytes. Query indicators are first averaged within each scenario. The stored analysis "
            "resamples complete scenario values, or within-scenario paired differences, 10,000 times with "
            "random seed 20260930 and reports percentile intervals. This preserves clustering among a "
            "scenario's three questions. Paired intervals are read directly from the accepted evidence.",
            "Secondary method comparisons, other budgets, sensitivity settings and median-split strata "
            "are descriptive. Their intervals are not adjusted for multiple comparisons. The parameter grid "
            "is fully reported, rather than used to promote an outcome-selected method to the primary hypothesis. "
            "A fixed protocol on previously used data does not confer independent confirmatory validation.",
            "Reader UIDs were selected by sorting a seed-and-UID SHA-256 digest within each dataset type, "
            "taking two per type. The protocol records seed " + protocol["seed"] + ". " + reader_text +
            " Readers see only selected history and the dimension-three query. The protocol explicitly disables "
            "the oracle intervention; its empty analysis entries are bookkeeping, not failed trials."
        ]},
        {"heading": "Primary Retrieval Results and Budget Dependence", "paragraphs": [
            arm_text + " The paired sentence-minus-turn new-state contrast is " + primary_text +
            ". This is a difference in percentage points, not a relative percentage change. "
            "It shows lower lexical containment for this sentence implementation on this reused dataset.",
            "The greater update-session coverage of sentence BM25 coexists with lower new-state inclusion. "
            "Reaching a session can therefore be a weak proxy for retaining its decisive sentence. The "
            "aggregate difference is consistent with changes to ranking and passage granularity, but these "
            "summaries do not isolate which mechanism caused it.",
            "The old/new panels show that a context may retain an old statement, a new statement, both "
            "or neither. An old statement can help explain a revision when both are present, so old-state "
            "inclusion alone is not an answer-error rate. The joint-state figure separates these cases "
            "instead of interpreting every retained old statement as a failure.",
            "The budget plot includes stored intervals for the two BM25 indexes and the two time/cue "
            "indexes, plus paired sentence-minus-turn BM25 contrasts at every tested ceiling. It reports "
            "the complete budget sweep rather than extrapolating the primary result to arbitrary context "
            "sizes. More bytes may increase lexical availability while leaving semantic answer quality unresolved."
        ], "tables": [primary_table], "figures": [
            figure("retrieval", "Old and new normalized exact inclusion at the primary history budget. "
                   "Bars and 95% intervals use scenario means; turn and sentence methods use the same cases."),
            figure("budget_comparison", "New-state availability across all tested budgets and stored paired "
                   "sentence-minus-turn contrasts. Shading and error bars show scenario-bootstrap intervals. "
                   "Budgets other than 4096 bytes are descriptive."),
            figure("joint_states", "Joint old/new containment at 4096 bytes. The four categories exhaust the "
                   "query records and are averaged within scenarios. Old-only containment is distinct from "
                   "retaining both statements and is not itself a graded response error.")
        ]},
        {"heading": "Sensitivity, Strata and Lexical Recoverability", "paragraphs": [
            "The time/cue grid varies alpha over 0, 0.1, 0.25, 0.5 and 0.75 and beta over 0, 0.1 and "
            "0.25 using the turn index at 4096 bytes. The heatmap displays every stored setting. "
            "Higher recency weights do not produce uniformly better new-state containment. The grid "
            "supports a diagnostic account of the implemented heuristic, not a newly validated optimum.",
            "Median-split analyses examine user-history byte length, median serialized user-turn length "
            "and relative update-session position. Low includes values equal to the cut; high is strictly "
            "above it. The table records cuts and denominators because ties make group sizes unequal. "
            "Intervals describe each stratum's paired unit contrast, not a formal test of interaction.",
            ceiling_text + " These are lexical recoverability measurements over concatenated role-specific "
            "text. The uncovered cases remain in the evaluation denominator. A paraphrase may still "
            "provide semantic support even without a literal or contiguous-token match.",
            diagnostic_text + " The stop variant's reduced fill follows from its declared packing rule. "
            "The unusually low RRF old-state rate is retained as an observation requiring targeted "
            "inspection. Neither its cause nor an implementation defect is established by this aggregate "
            "report. These diagnostics are not used to discard cases or revise the frozen primary contrast."
        ], "figures": [
            figure("sensitivity_strata", "Left: all time/cue settings, with inclusion percentages annotated. "
                   "Right: sentence-minus-turn differences in median-split strata, with stored intervals. "
                   "All panels are descriptive and not corrected for multiple comparisons.")
        ], "tables": [table(
            "Median-split strata for the primary new-state contrast. Cut units are bytes for history/turn "
            "length and a session-position fraction for update position. Delta and intervals are percentage points.",
            ["Stratum", "Cut", "N", "Delta", "95% interval"],
            [[row["field"].replace("_", " ") + " / " + row["side"], f"{row['cut']:.3f}",
              str(row["n"]), percent(row["mean"]),
              f"{percent(row['ci95'][0])} to {percent(row['ci95'][1])}"] for row in retrieval["strata"]])
        ]},
        {"heading": "Reader Pilot: Completion, Judgments and Missingness", "paragraphs": [
            reader_text + " Each scenario is answered under both BM25 contexts by both reader aliases. "
            "The reader instruction asks for a natural English response within 120 words that respects "
            "changes supported by history. API aliases do not independently authenticate a model's weights "
            "or revision, and the results are attached to this particular recorded run.",
            "The opposite model grades the reader's responses using an adapted dimension-three rubric: "
            "a final action or recommendation must adhere to the new state; outdated constraints and "
            "overly generic responses fail. Responses are assigned stable shuffled labels, without "
            "method or reader identity in the judging prompt. The judge receives gold states and hidden "
            "logic only at this grading stage. This is model adjudication with a rubric, not a human label.",
            pairs_text + " These intervals quantify empirical resampling uncertainty for the four "
            "observed paired cases per model. They do not support equivalence, generalization or "
            "a ranking of reader models. Reader and judge identities are coupled across models.",
            "The missing-data bounds coincide with point differences because every scheduled answer "
            "in this run was graded. They remain distinct from sampling intervals. In particular, an "
            "all-failure cell yields an empirical bootstrap interval of zero to zero; that is a "
            "degeneracy of resampling the observed outcomes, not proof of a zero population pass probability.",
            "All natural reader contexts in this sample lack a normalized exact new-state match. "
            "The new-present association group therefore has no observations, and no comparison of pass "
            "rates by evidence exposure can be estimated. A pass without an exact match may reflect "
            "paraphrased support, reader behavior or judge error; the current artifacts do not identify "
            "which explanation applies. Oracle comparisons were disabled by design."
        ], "tables": [reader_table, paired_table]},
        {"heading": "Discussion", "paragraphs": [
            "The primary finding is a negative unit contrast for literal update availability, despite "
            "better session coverage for the sentence index. The distinction matters when evaluating "
            "retrieval systems: a location-based metric can improve while the exact required statement "
            "becomes less available. Evaluation should specify both the target statement and the "
            "serialization policy, rather than equating any retrieved update-session text with success.",
            "This study changes indexing and packing together. Sentence segmentation changes document "
            "frequencies and length normalization, while sentence headers consume bytes and tie resolution "
            "changes which passages fit. A mechanism study would need separately fixed scoring or "
            "controlled passage transformations. The present results should be read as an implementation "
            "comparison rather than a universal argument against sentence retrieval.",
            "The reader pilot does not establish whether the retrieval difference transfers to usable "
            "answers. Its cases have no exact-match exposure contrast and the outcome sample is small. "
            "Stronger evidence would require a prospectively specified larger reader sample, a meaningful "
            "exposure contrast, semantic support annotations and human validation. Such experiments would "
            "need a new protocol rather than retroactive changes to the accepted run.",
            "Detailed presentation improves the auditability of existing results, but does not enlarge "
            "the study. The current rewrite adds method definitions, stored paired uncertainty, diagnostic "
            "plots and explicit denominators while preserving every reported outcome. It does not "
            "rerun retrieval or substitute historical V4 results for the independent project evidence."
        ]},
        {"heading": "Limitations", "paragraphs": [
            "Data reuse is the central inferential limitation. All retrieval scenarios belong to the "
            "same previously exposed public dataset; there is no fresh held-out population in this run. "
            "The frozen choices aid reproducibility, but exposure can influence the question and method set. "
            "Reported intervals describe empirical resampling of this dataset, not immunity to such bias.",
            "Exact and contiguous-token containment are lexical diagnostics. They can miss paraphrases "
            "and can count a statement without checking whether the reader interprets it correctly. "
            "Session containment is even coarser. The role-specific ceiling audit is also lexical and "
            "must not be interpreted as proving the absence of semantic information in assistant turns.",
            "The tested retrieval algorithms are sparse and fixed. Sentence splitting uses punctuation "
            "and newline boundaries; recency uses ordinal turn position rather than elapsed time. "
            "The code-specific tokenizer, change markers, rank ties and header costs affect results. "
            "Dense retrieval and learned reranking are absent, so external method superiority is unresolved.",
            "Reader grades cover a single dimension, four cases and fallible opposite-model judgments. "
            "No human adjudication, randomized evidence intervention or identifiable exposed/unexposed "
            "association is available. The oracle option was disabled. Secondary grid, strata and budget "
            "intervals are descriptive and their multiplicity prevents treating each interval as a discovery."
        ]},
        {"heading": "Conclusion", "paragraphs": [
            "On this reused STALE dataset, the stored paired comparison shows lower new-state containment "
            "for sentence BM25 than turn BM25 at the fixed primary byte budget. Higher update-session "
            "coverage does not rescue literal statement availability. Budget, packing and weighting "
            "diagnostics make the result inspectable, while the small reader pilot leaves response-quality "
            "transfer unresolved. This report provides a reproducible record of those bounded findings."
        ]},
        {"heading": "Reproducibility and Evidence Boundaries", "appendix": True, "paragraphs": [
            "The independent project is alice-stale-replication-01. Accepted retrieval and reader artifacts "
            "are read from its result manifests and checked against the recorded SHA-256 values before "
            "building. The pinned method sources are checked against the frozen protocol. All tables and "
            "plots are transformations of accepted summaries; no dataset retrieval, reader requests or "
            "judge requests are repeated during document construction.",
            "The retained model draft is an unreviewed intermediate artifact. This edited report corrects "
            "its conflation of exact and punctuation-insensitive matching, replaces approximate arm-CI "
            "subtraction with the stored paired interval, and explains that oracle trials were disabled. "
            "It avoids interpreting a low RRF rate as proof of a defect. Original project artifacts are "
            "preserved; editorial transformations occur in this output directory.",
            "Run the local build_document.py script with the project evidence in place. It produces "
            "document.json, paper.tex, the PDF, figure PNGs, a build manifest and a writing audit. "
            "The audit records input hashes and verifies that the historical V4 PDF and accepted project "
            "evidence were unchanged during the build. There is no automatic reviewer upload or submission.",
            "The primary-budget detail table is complemented by the full five-budget new-state table "
            "below. Every method remains present, including diagnostic variants. Bibliographic metadata "
            "for STALE follows the supplied reference manuscript; this editing pass performs no live "
            "literature search or external source validation."
        ], "tables": [table(
            "Complete new-state inclusion percentages across all evaluated history budgets. Secondary "
            "budgets are descriptive; full intervals remain in the linked retrieval summary.",
            ["Method"] + [str(budget) for budget in budgets],
            [[LABELS[method]] + [percent(indexed[method, budget]["new"]["mean"]) for budget in budgets]
             for method in LABELS])]},
    ]
    document = {
        "title": "Sentence versus Turn Retrieval under Byte Budgets: An Evidence Audit on STALE",
        "author": "Team Neng Gong Zhi Ren",
        "abstract": "Smaller retrieval units can fit more passages into a context budget, but this need not "
                    "preserve the statement that updates an older memory. We audit sentence and turn retrieval "
                    "on previously exposed STALE data. " + scope_text +
                    " The fixed primary sentence-minus-turn BM25 contrast in new-state containment is " +
                    primary_text + ". " + arm_text + " " + reader_text +
                    " The small opposite-model-graded pilot cannot establish answer-quality transfer. "
                    "Budget, joint-state, weighting and stratified diagnostics are reported with evidence hashes. "
                    "Results describe this implementation and reused dataset; semantic correctness and "
                    "performance on unseen conversations remain untested.",
        "sections": sections,
        "references": [
            {"id": "stale", "short": "Chao et al.(2026)",
             "text": "Hanxiang Chao, Yihan Bai, Rui Sheng, Tianle Li, and Yushi Sun. STALE: Can LLM Agents "
                     "Know When Their Memories Are No Longer Valid? arXiv:2605.06527v1, 2026.",
             "url": "https://arxiv.org/abs/2605.06527"},
            {"id": "bm25", "short": "Robertson and Zaragoza(2009)",
             "text": "Stephen Robertson and Hugo Zaragoza. The Probabilistic Relevance Framework: BM25 "
                     "and Beyond. Foundations and Trends in Information Retrieval, 3(4):333-389, 2009.",
             "url": "https://doi.org/10.1561/1500000019"},
        ],
        "claims": claims,
        "evidence": {name: {"path": str(path), "sha256": digest(path)} for name, path in evidence_paths.items()},
    }
    return document, evidence_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tex-binary")
    args = parser.parse_args()
    historical = ROOT / "paper/v4/paper.pdf"
    historical_hash = digest(historical) if historical.exists() else None
    document, evidence_paths = build()
    before = {name: digest(path) for name, path in evidence_paths.items()}
    tex_binary = args.tex_binary or os.environ.get("RESEARCH_LAB_TEX_BINARY") or shutil.which("pdflatex")
    pdf = compile_document(document, OUTPUT, tex_binary=tex_binary)
    if any(digest(evidence_paths[name]) != value for name, value in before.items()):
        raise ValueError("Evidence changed during build")
    if historical_hash is not None and digest(historical) != historical_hash:
        raise ValueError("Historical PDF changed during build")
    tex = (OUTPUT / "paper.tex").read_text(encoding="utf-8")
    if "{{" in tex:
        raise ValueError("Unresolved claim placeholder")
    audit = {
        "project": PROJECT.name, "retrieval_rerun": False, "model_calls": 0,
        "editorial_method": "Evidence-grounded supervisor rewrite; original model draft retained",
        "sections": len(document["sections"]),
        "tables": sum(len(section.get("tables", [])) for section in document["sections"]),
        "figures": sum(len(section.get("figures", [])) for section in document["sections"]),
        "primary": read_json(evidence_paths["retrieval"])["paired"],
        "input_hashes": before, "historical_pdf_sha256": historical_hash,
        "historical_pdf_unchanged": True, "pdf_sha256": digest(pdf),
    }
    write_json(OUTPUT / "writing_audit.json", audit)
    print(json.dumps({"pdf": str(pdf), "sections": audit["sections"], "tables": audit["tables"],
                      "figures": audit["figures"], "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
