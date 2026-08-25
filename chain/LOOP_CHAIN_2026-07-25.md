# The Loop Chain — GA4 click/filter instrumentation for hotin.ai (2026-07-25)

> Source: Abe wants to see exactly what people click on hotin.ai — which tabs, which 7d/60d
> filters, which repo/model/paper rows, whether they copy the install command or star the
> repo. GA4 (property 546946466) is already wired for page views (gtag.js live since
> 2026-07-21); this chain adds the custom-event layer on top and proves it end-to-end in
> production. Each loop has a self-contained prompt, evidence-based exit criteria, and a
> fixed inner structure. A loop's EXIT triggers the next. Nothing advances on vibes.
>
> **Pacing:** checkpointed — every loop EXIT stops for go/no-go before the next loop starts
> (production infra, real user traffic, not a throwaway).

## Loop anatomy

| Field | Meaning |
|---|---|
| `goal` | One sentence. The state change the loop exists to produce. |
| `prompt` | Self-contained instruction block — a fresh session could run it from this doc alone. |
| `accept` | Evidence-based exit criteria — a checkable artifact each. |
| `bound` | Max inner iterations before honest escalation. |
| `exit →` | The loop this one's completion triggers. |

## The ribbon

```
RE-PLAN   read this loop's prompt + current origin/main HEAD; cut a mini-plan for THIS loop
BUILD     implement in an isolated clone (see git-state protocol below), not the working tree
PIN       a live capture that proves the mechanism, not a unit test (no test runner here —
          the artifact is a real GA4 event on a real page load)
PROVE     deploy to production; drive the real site (browser); capture the network hit /
          GA4 Data API row as evidence
MEASURE   compare against the pre-loop baseline (event counts, or "0 custom events" → "N")
REVIEW    self-review the diff against docs/index.html's existing conventions (chip/badge
          classes, .winset structure) before it ships — no second human reviewer on this repo
MERGE     push to origin/main (triggers the repo's own CI/CD: Pages deploy + Cloudflare purge)
EXIT      verify each accept criterion against the LIVE site + evidence; write EXIT.md;
          checkpoint with the user
```

**Git-state protocol (every loop, not just the first):** this repo has another active session
landing concurrent commits on `docs/index.html` and `src/hotin/cli.py`. Before BUILD: `git
fetch origin main` and diff local vs origin. If they differ, work in a **fresh isolated clone**
of `origin/main` (not the dirty working tree) so the loop's diff is clean and reviewable, then
push straight to `origin/main` from that clone. Never `git reset --hard` the user's local
working tree (lesson from 2026-07-24: this destroyed uncommitted `--since` work once already).

**Bound + escalation (every loop):** max 2 failed PROVE runs per loop. At the bound: EXIT.md
with `status: AT_BOUND`, exactly which criteria are unmet and why, then stop.

## The chain

**Order rationale:** instrument before verify (can't prove what doesn't emit yet); verify
before the stretch loop (Search Console + the weekly agent are a different, larger scope and
depend on the user completing an external step — a human gate, not a code loop).

### L0 — INSTRUMENT (add the GA4 custom-event layer)
- **goal:** every meaningful interaction on hotin.ai (tab switch, 7d/60d filter, clicking a
  ranked result, copying the install command, starring on GitHub, scrolling a section into
  view) fires a named GA4 event with the params needed to answer "what do people click and
  which filters do they prefer."
- **prompt:**
  > In an isolated clone of `origin/main` for github.com/abe238/hotinai, add `gtag('event',
  > …)` calls to `docs/index.html`'s existing JS (near the tab-switch handler at
  > `document.querySelectorAll('[role="tab"]')`, the `.winset` handler at
  > `document.querySelectorAll('.winset')`, the `.copy-btn` handler, and a new
  > `IntersectionObserver` for `.panel` sections). Event schema:
  > - `tab_view` — params: `tab` (the eid: repos/rising/insiders/models/papers/news)
  > - `window_toggle` — params: `tab`, `window` ("7"/"60")
  > - `select_result` — params: `entity` (tab), `rank` (1-indexed), `item` (the repo/model
  >   slug or title text), fired on click of any `.row .name a` link (event delegation, one
  >   listener on `.board`, not per-row — rows are baked HTML that regenerates daily)
  > - `copy_install` — params: `command` (the copied text)
  > - `star_click` — no extra params, fired on the `.star-link` click
  > - `section_view` — params: `section`, fired once per section via IntersectionObserver
  >   (threshold 0.5), each section only fires once per pageview (guard with a Set)
  > Also register these 6 events + their params as GA4 **custom dimensions** via the Admin
  > API (`analyticsadmin.googleapis.com/v1beta/properties/546946466/customDimensions`) so
  > they're queryable — auth is keyless ADC, already logged in as abe.ai.bot@gmail.com (see
  > project memory `ref_hotin_analytics.md` for the exact curl/token pattern). Mark
  > `copy_install` and `star_click` as GA4 **key events** (conversions) via the Admin API.
  > Keep every listener defensive (never throw if `gtag` is undefined — e.g. ad-blockers).
  > Match the file's existing code style (no semicolons omitted inconsistently, `var`, IIFE
  > pattern already used in the script block).
- **accept:**
  1. `docs/index.html` diff shows all 6 event calls wired to their real DOM triggers (not
     stubbed) — reviewable in the PR/commit diff.
  2. The 6 custom dimensions + 2 key events exist on GA4 property 546946466, confirmed via
     `analyticsadmin.googleapis.com/v1beta/properties/546946466/customDimensions` GET
     returning them.
  3. Commit pushed to `origin/main`; CI (`.github/workflows/pages.yml` or `refresh.yml`)
     deploy succeeds for that SHA.
- **bound:** 2 PROVE runs (a PROVE run here = deploy + one browser pass).
- **exit →** L1.

### L1 — VERIFY LIVE (prove every event actually fires in production)
- **goal:** each of the 6 events is observed firing on the real hotin.ai, either in GA4
  DebugView (real-time) or via a `runRealtimeReport` Data API call, driven by an actual
  browser session (not curl — these are JS-triggered).
- **prompt:**
  > Using the claude-in-chrome tools, load `https://hotin.ai/` in a real tab. Drive: click a
  > second tab (tab_view), click a `60d` toggle then back to `7d` (window_toggle ×2), click
  > one ranked repo link in a new context so it doesn't navigate away the test tab
  > (select_result — or read `read_network_requests` for the `/g/collect` POST body instead
  > of actually navigating), click "copy" (copy_install), scroll to the bottom panel
  > (section_view). After each action, use `read_network_requests` filtered on `collect` to
  > capture the POST body showing `en=<event_name>` and the custom params (`ep.tab`,
  > `ep.rank`, etc. — GA4 encodes custom params as `epn.*`/`ep.*` in the collect payload).
  > Save each captured request body to `chain/evidence/l1-verify-live/`. Cross-check with one
  > GA4 Realtime Data API pull (`runRealtimeReport` on property 546946466, dimension
  > `eventName`) showing the new event names present with nonzero counts.
- **accept:**
  1. 6 distinct `/g/collect` POST bodies captured, one per event, each showing the correct
     `en=` value and the expected custom params — saved under `chain/evidence/l1-verify-live/`.
  2. A `runRealtimeReport` API response (saved as JSON evidence) shows at least the events
     driven in this loop with count ≥ 1, distinct from the pre-loop baseline (`page_view`,
     `first_visit`, `session_start`, `scroll` only — captured 2026-07-24, see prior-session
     transcript for the baseline numbers).
  3. No `select_result` param crosses PII/secret boundaries — the `item` value is only the
     public repo/model slug already shown on the page (self-review checkpoint, not a
     separate tool).
- **bound:** 2 PROVE runs.
- **exit →** L2 (human gate).

### L2 — RE-PLAN GATE (human gate — Search Console + the weekly agent)
- **goal:** verdict on L0+L1 with numbers, and — pending Abe's go-ahead — draft the next
  chain for the two stretch items from the original ask: (a) Search Console verification
  (needs a Cloudflare DNS TXT record Abe didn't hand over yet) and (b) the weekly
  pull→analyze→improve→report agent (a materially bigger build: GA Data API + Search
  Console API + PageSpeed pulls, an LLM analysis pass, a change-budget guardrail, and a
  scheduled runner).
- **accept:** verdict doc (this chain's running delta table, below) presented to Abe; his
  sign-off on whether L2 continues into the stretch chain now or later. No trace can
  substitute for this — it is the one criterion that is inherently a human decision.
- **bound:** 2 drafts of the stretch-chain proposal; the sign-off wait itself is unbounded.
- **exit →** the next chain doc (successor file), only after sign-off.

## Parallel track (interleave, don't serialize)
None for this chain — L0 and L1 are small enough and sequential-by-nature (can't verify what
isn't built yet) that a parallel track would add coordination overhead for no wall-clock win.

## Chain invariants
0. Plan before build — this doc exists before any BUILD step ran.
1. No loop advances without its EXIT.md — criterion → evidence pointer, verified at HEAD.
2. Deltas are cumulative — each EXIT.md carries the running L0→Ln table.
3. Regression = unmet criteria, even if the loop's feature "works."
4. AT_BOUND is a first-class exit — write it honestly, page the user, stop.
5. Instrument failures (e.g. a Cloudflare cache serving stale JS) don't count as evidence
   failures — diagnose, fix in its own commit, document in the bound accounting.
6. Human gates pause the chain — L2 waits unbounded for Abe.
7. ZEN check on every BUILD — the event *names/params* are a product decision already made
   in this doc; the code implementing them is mechanical.
8. This chain doc is append-forward; a redirect or the L2 stretch chain gets a successor
   file, not an edit to this one.
