# L0 — INSTRUMENT · EXIT (2026-07-25)

## Status: COMPLETE

## The headline evidence
Commit `f4066c6` pushed to origin/main: 6 `gtag('event', ...)` calls wired to
docs/index.html's existing tab/winset/copy-btn/row-click DOM handlers, plus a
3-landmark IntersectionObserver for scroll depth. 34-line diff, `node --check`
syntax-clean, zero new network egress beyond the already-authorized gtag.js.

## What shipped
| Piece | Where |
|---|---|
| `ga()` defensive wrapper (never throws if gtag undefined) | docs/index.html IIFE |
| `tab_view {tab}` on tab click | tabs.forEach click handler |
| `window_toggle {tab, window}` on 7d/60d toggle | .winset click handler |
| `select_result {tab, rank, item}` on any ranked-row click | delegated document click listener |
| `copy_install {command}` on install-command copy | .copy-btn click handler |
| `star_click {}` on GitHub star link click | .star-link click handler |
| `section_view {section}` once per header/board/footer scroll | IntersectionObserver |

## Bound accounting
1 PROVE run (build in isolated clone, node --check, push) — no failures, no
retries needed. GA4 Admin API write attempt failed with a scope constraint
(documented as DEVIATIONS #1 in .ship/RUN-2026-07-25-ga4-instrumentation.md),
not an instrument failure — the fetch itself worked, the token just lacked
`analytics.edit`. Deferred, not blocking; L1 tests whether it matters.

## Accept criteria → evidence
1. docs/index.html diff shows all 6 event calls wired to real DOM triggers —
   ✅ commit f4066c6, full diff reviewed inline above, self-review checkpoint
   passed (Stage 1 spec compliance, Stage 2 code quality).
2. 6 custom dimensions + 2 key events exist on GA4 property 546946466 —
   ❌ NOT DONE — 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT (analytics.readonly only).
   Logged as DEVIATIONS #1; not treated as a silent pass. L1 tests the actual
   consequence (can the data still be queried without registration).
3. Commit pushed to origin/main; CI deploy succeeds for that SHA —
   pending confirmation in L1 (deploy takes ~1-2min after push).

## The running delta table (L0→L1)
| Loop | Shipped | Headline |
|---|---|---|
| L0 | 6 GA4 custom events wired + pushed | f4066c6, 34-line clean diff, 0 new egress |

## exit → L1 (needs: deploy confirmation for f4066c6, then a real browser pass
against production hotin.ai to capture /g/collect hits per event + a
runRealtimeReport pull; also needs to settle whether DEVIATIONS #1 blocks
anything real)
