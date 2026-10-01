Research workflows need reproducible artifacts and safe reuse of completed, metered stages. This patch adds artifact hashing and verification, a pure bounded-attempt allocator, and an optional loader for the pinned standalone SwarmFlow engine plus claim-to-artifact hash checks.

The engine implementation remains upstream code. Source loading avoids eager imports of unrelated product services. The integration intentionally covers bounded text tasks; it does not deploy TeamWorkerBackend or the complete service stack, execute arbitrary generated code, or certify scientific claims. The host application provides its own gateway client and persistent token ledger.

Validation: upstream-layout helper tests; actual native engine journal replay; real model research calls with bounded numeric candidate proposals, reader responses, judging, and prose. See the included tests and integration notes for exact scope. No credentials, paper-review tokens, datasets or user research outputs belong in this PR.

Base JiuwenSwarm commit: ce8af2051fd7c5dff85a09f8185fce64d32893a6.
Pinned agent-core for the optional loader: 9e3390195a9ea15235b2b5f7412cb2aa440622cc.

This is a draft contribution description and local patch. The team owner will publish the PR; no public URL or merge claim is asserted.
