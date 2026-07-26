# L4 — dry run against real accumulated data (the named human gate)

Per chain/LOOP_CHAIN_2026-07-26.md L4: "running the floor logic against the
real clicks.json/tags.json accumulated by this point in the chain produces a
patterns.json whose confirmed list (if any) is manually checked against the
raw click data and found honest — this is the named human gate for L4."

Weekly workflow dispatched manually (run 30188185820, commit 124c3ba) against
the real, live docs/data/clicks.json and docs/data/tags.json.

## Result: 0 confirmed, 0 watchlist

```json
{
  "_schema_version": 1,
  "_caveats": ["near-duplicate entity_ids ... not detected ..."],
  "_untrusted_fields": ["tag", "entity_id", "referrer_domains"],
  "confirmed": [],
  "watchlist": []
}
```

## Cross-check against raw click data

`clicks.json` currently has exactly ONE item with any recorded activity:
`mikiarlo3/ai-copywriter`, 1 session, tag `uncategorized`. That's the
single real click made while manually verifying L1's join-key fix earlier
in this chain. Everything else is still `BREAKDOWN_PENDING` or genuinely
zero — hotin.ai has had very little real traffic since instrumentation
shipped hours ago, and GA4's processing lag means even that traffic is
still catching up.

**This is the correct, honest output.** 1 item at 1 session is nowhere near
MIN_ITEMS=3 / MIN_SESSIONS_PER_ITEM=3, so nothing should confirm and nothing
should even reach the watchlist (which requires clearing the per-item floor
first). The gate is not producing false positives on thin data — it's
correctly reporting that there isn't enough real evidence yet to claim
anything, which is exactly what a trust floor is supposed to do at this
stage.

## What this dry run does NOT prove
It proves the floor doesn't fabricate patterns out of thin data. It does
NOT yet prove the confirm path fires correctly on real traffic, since real
traffic hasn't accumulated yet — that will only be verifiable once genuine
click volume builds up over the coming days/weeks (the same honest
data-maturity gap acknowledged throughout this whole chain). The 13
synthetic guardrail tests in tests/test_statistical_floor.py (referrer
diversity, item-count floor, near-duplicate dedup, stale-tag correction,
uncategorized exclusion) are what verify the CONFIRM path's correctness
today; this dry run verifies the NO-FALSE-POSITIVE-ON-THIN-DATA path against
real data specifically.
