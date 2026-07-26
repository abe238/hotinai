# L1 — live verification

Commits: 747aeb2 (T0 scaffold) -> ce5cb29 (T1a/T1b/T1c) -> 5ff51c4 (join_id length cap).
Live refresh.yml runs: 30185726499 (success), 30185903258 (success, after the
join_id fix). CI green on both commits (all 6 matrix legs).

## GA4 custom dimension
`id` registered (properties/546946466/customDimensions/15324742396), alongside
the 6 already live from 2026-07-25.

## tags.json (post-bake, commit after run 30185903258)
- 279 items tagged across repo/model/paper/news entity types (previously
  repo-only). Distribution: agents 85, uncategorized 113, creative-media 23,
  training 22, inference 19, dev-tools 10, app-building 7.
- Papers/models both got real, non-uncategorized tags in most cases
  (e.g. `baidu/Unlimited-OCR` -> app-building, correctly catching "OCR").
  News is honestly thinner (headline-only text) — many uncategorized, as
  documented; this was a known, accepted limitation from the design.

## Join-key fix (the L0-flagged gap)
- `docs/index.html`'s `select_result` handler now sends `id` alongside `item`.
- Every board row carries `data-id` from `board.py`'s new `id` field.
- **GA4's 100-char event-parameter cap (Standard property, verified via
  Google's own docs) would have silently truncated 8/60 news article-URL ids
  in the very first live bake** — caught empirically, not theoretically, by
  inspecting the real `latest.json` after the first bake. Fixed with
  `board.join_id()`: 0/60 news ids exceed 80 chars post-fix, 19 got hashed to
  a short stable key, and every hashed key resolves correctly in `tags.json`
  (spot-checked 3, all present with a real tag) — both sides of the join
  derive the key identically.

## Review
Blind code-reviewer pass (opposite-family, gated per the task contract)
found 2 real blockers before this landed: `_write_tags_json` could raise on
a malformed prior file (fixed: broader exception handling + moved the write
to run last, after the board bake, wrapped in try/except so tagging can
never cost the site its daily refresh) and vocabulary widening flipped
existing repo classifications (bare "efficient"/"planning"/"reasoning" fired
on unrelated prose — fixed, regression-pinned in tests/test_categories.py).
Also fixed on the reviewer's non-blocking findings: `rising7` was unclassified,
model_task now feeds classify() as a topic.

## Tests
266 passing (251 baseline + 15 new: 5 in test_board.py, 5 in test_tags.py,
3 in test_categories.py regression pins, 2 in test_render_board.py).
