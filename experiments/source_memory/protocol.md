# Byte-bounded source memory: protocol v1

Supervisor-authored before quantitative experiments, 2026-09-29.

Question: under an equal serialized-byte ceiling, how do provenance, revocation,
version checks, completeness gating and tombstone retention trade stale answers
against accuracy? This is a controlled synthetic mechanism study.

## Semantics

Two declared sources a,b have equal authority. A put event [P,k,s,v,x] asserts
value x at positive version v. A revoke [R,k,s,v,null] invalidates that exact
version; revocation is permanent and can arrive before a replay of its put.
For each source, the highest put or revoked version is current. A revoked
current version contributes no value; an earlier version never revives.
Multiple distinct current values yield CONFLICT; none yields UNKNOWN; a singleton
yields that value. These labels differ from ABSTAIN (insufficient retained
evidence). Replay of a lower version cannot overwrite a retained higher version.
Queries arrive only after the stream. Policies never see the query during writes,
the full oracle state, family name, correct answer, or random seed.

Version numbers are local to (key,source), never globally comparable. `latest`
is an intentionally source-blind weak diagnostic: it replaces on every arriving
put, and clears on a revoke whose number is at least its stored number, regardless
of source. It can revoke another source's state. Do not treat it as a correct
source-aware baseline or attribute all differences from it to eviction. The main
paired comparisons are gated vs source and protected vs gated, not latest.
Gating ensures only that both source slots are retained, not that they are fresh
or correct. Equal-authority conflicts never use a cross-source last-writer rule.

## Policies and cost

event_window: suffix of raw events; replay only that retained suffix at read time.
latest: arrival-latest per key, deliberately collapses sources, processes revokes.
source: LRU slots per (key,source), versions and revocations, no completeness gate.
no_revoke: source with revocation events ignored.
no_version: source with arriving puts allowed to replace newer versions.
gated: source, but ABSTAIN unless both declared sources have retained slots.
protected: gated plus eviction of oldest positive slot before any tombstone.

source/gated/protected use the same four fields [key,source,version,value], null
for tombstones. latest uses [key,"*",version,value]. event_window uses raw five
fields. JSON compact separators, UTF-8, ensure_ascii=False; brackets and commas
count. All persistent task state is exactly the serialized list, including LRU
order; no free index, forgotten-key set or hidden watermark. Measure after every
event; evict from the front until at most B bytes. Peak temporary ingest allocation
and Python heap size are not claimed to be bounded. Query-time event-window
reduction is read computation, not retained memory. Completeness does not prove
freshness after an evicted watermark: report replay failures rather than hide them.

Budgets B = 384,768,1536 bytes. Same ceiling, not same filled size or tokenizer
cost. Comparison includes metadata overhead and actual retained-byte statistics.
No natural-language extraction or summarization component is being evaluated.

## Data, splits, outcomes

Six equally weighted families: steady, update, revoke, conflict, resolve, replay.
Each seed generates 120 traces (20 per family) and one end query per trace. A
query key is randomly chosen; all keys start with equal values from both sources.
Irrelevant updates/revocations create memory pressure. Critical transitions are
inserted with lags in {0,4,12,36}. Standard uses 12 keys and compact identifiers.
Stress shift (seeds >=10000) uses 24 keys, 128 background events and longer keys/
values. This is a generator-controlled stress shift, NOT an independent real-world
benchmark or semantic transfer test. Seven hand-audited semantic fixtures plus a
cross-source collision diagnostic are separate checks.

Development seeds: 11,23,37. Held-out seeds: 101,211,307,401,503,607,709,809,907,1009.
Stress seeds: 10101,10211,10307,10401,10503,10607,10709,10809,10907,11009.
Methods and budgets fixed here; no candidate selection on holdout. Freeze source
and protocol hashes after tests/development, before held-out evaluation.

Primary: stale-answer rate over ALL queries: concrete returned value appeared
historically for the query key but is no longer among oracle's active values.
Do not call one side of a live conflict 'stale'; separately report false concrete
answers on conflict and overall exact accuracy. Guardrails: accuracy, ABSTAIN
rate, concrete-answer recall on singleton truths, UNKNOWN and CONFLICT accuracy.
All-ABSTAIN diagnostic has stale=0 and accuracy=0 and is explicitly discussed.
Report paired differences by seed and 95% percentile bootstrap CI, 10000 draws
with fixed analysis RNG 20260929. Seeds, not individual trace/method rows, are
resampling units. CI is descriptive; no post-hoc significance mining.

## Model-reader pilot

After the deterministic freeze, select the first 12 traces of seed 101 in original
order (two of each family), at B=768. For each configured model, evaluate the same
traces with event_window, source and protected memory: 72 planned calls total.
Models see retained memory, query and policy's public representation semantics,
but no oracle label, family, deterministic prediction or full history. Ask for one
JSON answer. max output 1800, one network attempt per task; errors/truncations are
reported and count incorrect; no selective retry. This small convenience slice is
an illustrative reader pilot, not a powered comparison of foundation models.
The two configured model identities are gateway-reported aliases, not independently
verified weight identities. Real API usage and failures enter the persistent ledger.

## Integrity and authorship

Research topic, protocol, trusted implementation and acceptance are supervised by
Codex. DeepSeek proposes bounded test cases and prose; Kimi audits bounded design/
evidence questions. Their opinions can be rejected. No generated code is blindly
executed. Model calls, inputs, outputs, decisions and hashes are preserved. The
existing modified JiuwenSwarm manifest module verifies all grid artifacts. The
result is a semi-automated research workflow; full SwarmFlow service is not claimed.
