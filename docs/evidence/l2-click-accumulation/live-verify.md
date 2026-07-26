# L2 — live verification

Commits: 1570874 (pull_clicks.py + refresh.yml wiring). CI run 30186352562
(macos·3.14 leg flaked on an unrelated pre-existing timing test in
test_engine.py — `assert elapsed < 0.15`, last touched in f768a3f, nothing to
do with this diff; confirmed flaky by rerun, which passed clean; all 6
matrix legs green after rerun). Refresh run 30186438898: success.

## Secrets
GA_REFRESH_TOKEN / GA_CLIENT_ID / GA_CLIENT_SECRET added as repo secrets
(Abe's explicit choice over the local-pull alternative — see conversation).
Confirmed correctly masked (`***`) in the live CI log, and the pull step ran
successfully end-to-end in the actual GitHub Actions environment (not just
locally): `pull_clicks: folded 0 (item, day) cells (0 items tracked total)`.

## Review-caught bug (real, serious, fixed before shipping)
Original design added each 3-day-window GA4 total on every 3-hourly run —
verified independently by both the reviewer and a local repro that a single
click stayed inside the rolling window for ~24 runs and got counted ~24x,
non-uniformly. Rewritten to key the ledger per-day and ASSIGN (not add) each
day's GA4 total — idempotent by construction. Pinned in
tests/test_pull_clicks.py::test_refolding_the_same_day_is_idempotent_not_additive
(24-run replay of the same day, asserts no inflation).

One reviewer-cited blocker did NOT hold up: the claim that `docs/data/clicks.json`
doesn't exist at HEAD (so `git add` would fail with a pathspec error) was
checked against a stale local clone, not the real repo — the file was already
scaffolded and committed in L0 (747aeb2). Verified directly against origin/main
and again against the live CI run's own `git add` step, which succeeded.

## Two-pass / honest-lag verification (live data)
- Total select_result events in the 3-day window: 1 (a pre-fix click, id
  reported as `(not set)`) — correctly folded to 0, not miscounted.
- A fresh, real click (dispatched via direct DOM event on the live site,
  confirmed to build the exact payload `{id, item, rank, tab}` and send it to
  gtag) had not yet appeared in GA4's reportable id-breakdown at verification
  time — expected processing latency, not a bug; the next run naturally picks
  it up once GA4 finishes processing.

## Tests
277 passing (266 baseline + 11 new in test_pull_clicks.py, including the
idempotency pin and a stale-day roll-off test).
