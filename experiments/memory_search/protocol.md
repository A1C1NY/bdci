# Local synthetic memory protocol v2

This is an engineering benchmark written for this repository, not a publication.

Each seed generates 120 independent episodes, each containing 72 events. There
are 16 possible keys. With probability 0.65 an event updates a key with a new
integer value; otherwise it is a distractor. The query is sampled from keys
which have appeared. The target is that key's latest value.

All methods ingest the same events before seeing the query and use at most
eight records. `recent_window` retains all event types; `events_only` removes
distractors but keeps redundant updates; `keyed_memory` stores the newest value
per key and refreshes its eviction position; `fifo_memory` overwrites values
without refreshing insertion order. `first_write` freezes the first value of
each retained key, removing the overwrite mechanism from keyed memory.

Predictions receive events and query only, never the target answer. Correctness
is calculated outside the predictor. Actual retained-record counts and JSON
serialized byte counts are reported; record equality does not imply byte or
token equality. Dataset identity includes complete tasks and targets and is
shared across methods for a seed.

Development and holdout seeds, candidate order, threshold, metric and budgets
are preregistered in campaign.json. Selection is frozen before holdout jobs.
The holdout compares baseline, frozen selection and first-write ablation.
The controller does not choose another method based on holdout outcomes.
