# L1 — SOURCE ADAPTERS · EXIT (2026-07-20)
## Status: COMPLETE
## Headline
All 8 adapters built (github, trends, hn, npm, reddit, youtube, smartmoney, x-stub) +
throttle.py's shared politeness primitive. 110 tests green. Every adapter live-verified against
its real API by hand, not just its own mocks — including the two hardest cases: smartmoney's
pure-Python the influencer-stars source RSC scrape (caught the influencer-stars source mid-URL-drift: /ai/... -> /tech/... redirect) and
youtube's ScrapeCreators integration (found + fixed a structural bug that made it permanently
return zero records).
## Two real process/infra failures, both root-caused and fixed durably
1. First parallel batch of 6 adapters collided into one shared codex session (parable-run.sh
   derives session identity from the plan file's PARENT DIRECTORY by default) - only reddit.py
   was actually built; the other 5 were silently no-ops. Fixed: explicit --slug per dispatch.
2. A fix-round dispatch was killed by the OS mid-run with no session_id (nothing to resume).
   Investigated live (not sleep, no leaked process, no definitive log entry, but real memory
   pressure present); retried cleanly with zero changes. Fixed durably: chain/resilient-dispatch.sh
   auto-retries any parable-run.sh dispatch up to 3x on a non-OK result.
## Bound accounting
2 cross-model (Sol) review rounds: build review (1 P1, 5 P2, 1 P3 on L0, separate loop) and this
loop's adapter review (2 P1, 3 P2, 1 P3). Every finding independently reproduced by hand before
and after the fix (not just re-running terra's own tests):
- P1: stereo2spatialGithub glued-text bug, confirmed live in reddit/hn/youtube, root-caused to
  the exact raw source text (zero separator between URL and next sentence), fixed with a
  camelCase-boundary heuristic, re-verified correct in all three post-fix.
- P1: youtube missing includeExtras=true meant description field never present -> permanently
  zero records regardless of real content. Verified live before (0 records, wrongly assumed
  "expected") and after (8 real records: lobehub/lobehub, ai-builder-club/sk, etc).
- P2: committed the influencer-stars source fixture had real people's names/bios/social IDs - replaced with synthetic
  data, re-scanned clean.
- P2: reddit's query param was silently discarded - added /search routing, live-verified (real
  API call, correctly-empty result when no post in the result set had a link).
- P2: youtube reported "ok" on zero records - now "empty".
- P3: smartmoney's row-detection rejected an entire valid list over one bad row - loosened to
  majority-tolerant, hand-verified [valid, None, valid] -> 2 records.
## exit -> L2 (the ranking engine): corroboration, freshness, credibility, categories, scoring
