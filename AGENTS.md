# Working on the team handoff repository

This is the public development checkout, not the team's frozen competition archive.

- Read README.md and docs/TEAM_HANDOFF.md before running research. Legacy projects remain supervised. Autonomous modes follow docs/AUTONOMOUS_RESEARCH.md and docs/OPEN_TOPIC_RESEARCH.md and record machine reviews as machine decisions; never fabricate human acceptance, evidence, reviewer scores or submission success. Open topic selection must respect the installed executor registry and shared campaign budget; metadata discovery is not full-text verification or proof of novelty.
- Use Python 3.12 and requirements.lock. Bootstrap pinned upstream source with scripts/bootstrap.py; do not commit vendor/ or silently upgrade pins.
- Keep credentials, reviewer access tokens, original model responses, datasets, project state, papers and submission archives out of Git. Scan the staged index with scripts/check_share.py before pushing.
- Offline fixtures and tests do not need API credentials. Real calls require a configured personal budget and user authorization; pass --allow-models only within that authorization. Keep unknown usage reservations and failure records.
- Use unique project IDs. Do not overwrite old research or use historical V4/V5 tokens for new PDFs. When changing an experiment, preserve the protocol, code commit and all outcomes.
- Review-bound decisions must use the current binding and a substantive reason. Fixture auto-acceptance is limited to explicitly synthetic tests. Autonomous real research requires actual model reviews over bound evidence, trusted domain evaluators, frozen budgets and a one-way formal-evaluation barrier. Do not transplant fixture decisions into real runs.
- Changes to adapters must preserve project-local artifact paths, source hashes, independent budget admission and read-only dashboard behavior. Add meaningful tests for cross-project isolation and recovery when relevant.
- Run python -m pytest -q and the relevant local fixture. On Windows set PYTHONUTF8=1; if sandbox temporary-directory permissions fail, use an authorized writable test directory.
- Do not submit to the competition, upload a paper to a reviewer, publish an upstream PR, or invite collaborators unless requested. Ordinary repository development/push authorization does not authorize those separate actions.

No private keys, credentials, or privileged data should be placed in this file.
