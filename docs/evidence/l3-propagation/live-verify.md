# L3 propagation — live verification

Commits: 1d58dec (propagation mechanism, review fixes applied before ship).
CI run on 525ed61: green (6/6 matrix). Refresh run 30187701188: success,
full pipeline (pip install torch/sentence-transformers + compute_embeddings
+ surface_exemplar_candidates + propagate_tags) ran cleanly in the real CI
environment:
```
compute_embeddings: 1 newly embedded, 280 items total, 0 exemplars preserved
surface_exemplar_candidates: 0 new candidate(s), 0 pending total
propagate_tags: 0 item(s) tagged via exemplar propagation
```
Correct cold-start behavior: no exemplars confirmed yet (nothing to propagate
from), no click-volume candidates yet (clicks.json still thin), both honest
no-ops rather than fabricated activity.

## Local end-to-end dry run (before shipping, reverted after)
Confirmed the review-caught merge fix actually works: `approve_exemplar.py`
promoted one exemplar, `compute_embeddings.py` was re-run twice afterward
and both times reported "1 exemplars preserved" (not wiped), and
`propagate_tags.py` correctly tagged 15 items from that one exemplar with
confidence scores matching the L3 tracer's earlier measurements (0.41-0.58
range). Re-running `compute_embeddings.py` a third time with an unchanged
corpus reported "0 newly embedded" — the idempotent no-op path works.

## Review — real bugs caught and fixed before shipping
A blind gated review (opposite-family, high-effort given the `gnarly`
classification) caught the single most consequential bug in this epic so
far: `compute_embeddings.py` originally wholesale-overwrote the `exemplars`
map on every write. Since the script now runs every 3h in CI, the very next
run after a human confirmed an exemplar would have silently destroyed that
irreversible human input — with the pipeline reporting success throughout.
Fixed by switching to merge semantics (matching tags.json/clicks.json's
existing pattern). Also recalibrated NEAR_DUP_THRESHOLD (0.85 sat inside the
tracer's own observed duplicate band of 0.77-0.92) and bounded the
propagate-side re-verification queue append. Two other review claims were
checked against a stale local clone and did not hold against the real repo
(board rows already carry `id`; the ledger files were already tracked) —
verified directly before dismissing either.

## Tests
311 passing (301 baseline + 10 new: merge/preserve/idempotency coverage in
test_compute_embeddings.py, plus the consensus-margin and near-dup
recalibration pins added to test_propagate_tags.py).
