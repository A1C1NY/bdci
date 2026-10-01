# Add opt-in artifact integrity manifests and research attempt admission

Long-running research workflows need to detect replaced or missing evidence when a workspace is resumed or moved. File existence alone does not establish that an artifact still matches the recorded experiment. Separately, per-task retry limits do not bound cumulative admitted attempts across a research campaign.

This change adds explicit, opt-in helpers to JiuwenSwarm:

- `build_artifact_manifest` and `verify_artifact_manifest` in `common/team_artifacts.py` record relative paths, byte counts and SHA-256 digests. Verification detects missing or modified files and rejects malformed, duplicate and escaping paths.
- `common/research_budget.py` provides pure, serializable attempt/timeout admission. The caller owns locking and must persist a reservation before starting work. Crashes and retries do not refund reservations.

Existing workspace allocation behavior is unchanged. These helpers do not provide signatures, guarantee scientific validity, track API tokens, or enforce a hard total elapsed-time deadline.

Validation against commit `ce8af2051fd7c5dff85a09f8185fce64d32893a6`:

- Nine targeted helper tests pass, covering relocation, content changes, missing files, traversal, duplicates, malformed manifests, immutable reservations and admission limits.
- The local research integration replayed 483 CPU jobs / 57,960 predictions after moving an independently extracted submission bundle; all artifact checks and predictions matched.
- After installing `ruamel.yaml` into a project-local test directory, all 21 targeted helper and upstream artifact allocator tests pass (0.57 s). Full JiuwenSwarm services and SwarmFlow deployment were not exercised. This is an additive helper contribution, not a claim of upstream production integration.

The proposed changes and upstream-layout tests are in `contribution_with_tests.patch`. The contribution consists only of helper source and tests; it contains no unpublished paper, model credentials, reviewer token, or personal contact information.
