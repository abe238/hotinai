# L1 — VERIFY LIVE · EXIT (2026-07-25)

## Status: COMPLETE (with a corrected finding — see below)

## The headline evidence
Live browser pass against production https://hotin.ai/ (deployed commit f4066c6,
Cloudflare-purged). Drove: repos tab click, 60d toggle, cmd+click a ranked repo
row, copy-install click, cmd+click the star link. GA4 Realtime API
(`runRealtimeReport`, minuteRanges last 10) confirms ALL 6 custom events landed
server-side (chain/evidence/l1-verify-live/realtime-report.json):

    click 2 · page_view 2 · copy_install 1 · section_view 1 · select_result 1 ·
    session_start 1 · star_click 1 · tab_view 1 · window_toggle 1

## Correction to a claim made mid-epic (honesty over a clean narrative)
DEVIATIONS #1 (in .ship/RUN-2026-07-25-ga4-instrumentation.md) claimed the Data
API's `customEvent:<name>` dimension syntax works WITHOUT registering a custom
dimension first. **This was tested and is FALSE.** Both `runRealtimeReport` and
`runReport` return `400 Field customEvent:tab is not a valid dimension` for an
unregistered param — confirmed with two separate live API calls, not assumed.

**Practical consequence:** the events fire and are counted by NAME (proven
above — useful on its own: "how many tab switches happened", "how many
installs copied"). But breaking down BY parameter value (which tab, which
rank, which repo) — the actual "what do people click most" signal Abe asked
for — is NOT queryable via the Data API until the 6 custom dimensions are
registered via the Admin API, which needs `analytics.edit` scope (see L0
DEVIATIONS #1 for why that write failed with the current ADC login).
Un-corrected, this would have shipped a false "you're all set" — flagging it
now, at L2, before declaring the epic done.

## What was verified
| Piece | Evidence |
|---|---|
| Events reach GA4 servers | realtime-report.json — 6/6 custom event names present, count ≥1 |
| tab_view carries the right param | collect-hits.txt hit #1 — `ep.tab=repos` visible in URL |
| No unauthorized egress | only google-analytics.com + the two clicked github.com destinations (both user-initiated) |
| Param-level querying claim | RETESTED, corrected: needs analytics.edit + registration, contrary to earlier claim |

## Bound accounting
1 PROVE run (browser pass) — succeeded on the first attempt, all 6 events
present. 2 follow-up API calls to test the customEvent: claim — both returned
consistent 400s, which IS the answer (not an instrument failure to retry).

## Accept criteria → evidence
1. 6 distinct /g/collect hits, one per event — PARTIALLY via network capture
   (tab_view visible directly; others batched into POST bodies my tool can't
   read) — but ✅ via the authoritative server-side Realtime report instead,
   which is the criterion's actual intent (proof GA4 received them).
2. runRealtimeReport shows the driven events with count ≥ 1, distinct from
   the 2026-07-24 baseline (page_view/first_visit/session_start/scroll only) —
   ✅ realtime-report.json, 9 distinct event names now vs 4 baseline.
3. No PII/secret crosses the `item` param — ✅ self-review: item is only the
   public repo/model slug already rendered on the page.

## The running delta table (L0→L1)
| Loop | Shipped | Headline |
|---|---|---|
| L0 | 6 GA4 custom events wired + pushed | f4066c6, 34-line clean diff |
| L1 | Live-verified all 6 fire + are recorded | realtime-report.json: 9 event names, 6 new |

## exit → L2 (human gate). Abe needs to decide: grant analytics.edit (one
browser click, config-only, spans both his GA properties) to unlock param-level
Data API queries — or accept event-NAME-only querying for now and revisit
later. Either way this loop's own goal (prove the events fire in production)
is met; the scope question is a separate, correctly-deferred decision.
