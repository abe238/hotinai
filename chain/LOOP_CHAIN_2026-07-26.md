# LOOP CHAIN — hotin instrumentation (pattern-mining data layer)

Pacing: **checkpointed** — every loop EXIT is a stop for Abe's go/no-go. This
is new persistent state (the repo's first step away from zero-backend, a
trade Abe explicitly accepted), and L3/L4 make claims ("this is a confirmed
pattern") that must not go live silently.
Target repo: **github.com/abe238/hotinai**. Source: Abe-approved
`~/.config/hotin-analytics/design-2026-07-26/design.html`, deepened by
`~/.config/hotin-analytics/ideate-2026-07-26-semantic-pattern-mining/candidates.yaml`.
Human gates: after every loop (checkpointed pacing), plus a named hard gate
before L3 and before L4 go live (see those loops).

## Mission
Turn hotin's existing click instrumentation (shipped 2026-07-25) into
something that understands *what each item is about* and *which topics are
independently proven*, so a future newsletter can say "people gravitate
toward agent-orchestration tools" and mean it — without adding a database or
a live server.

## Scope
**In scope (this chain):** design steps 1–4 — all-entity tagging, click
accumulation into `clicks.json`, embedding-based exemplar propagation, and
the N-independent-items statistical floor (`patterns.json`).
**Deferred, not this chain:** design step 5 (newsletter draft generator) —
Abe flagged it lower priority; L5 below is a re-plan gate that decides
whether it becomes the next chain. **Explicitly out of scope:** wiring
`docs/dashboard.html` into the live site/nav — Abe deferred that separately.

## Baseline findings (measured before writing this chain, not assumed)
1. **CI concurrency is already safe.** `.github/workflows/refresh.yml` has
   `concurrency: {group: hotin-refresh, cancel-in-progress: false}` — GitHub
   Actions queues overlapping runs of this workflow rather than running them
   concurrently, so the "cross-dock JIT" race risk flagged in the ideate run
   (two runs racing a read-modify-write on the tags ledger) is already
   structurally prevented, **as long as every new ledger write stays inside
   this same job**. L0 re-verifies this at HEAD, doesn't re-litigate it.
2. **The click→item join key does not exist yet — this is the load-bearing
   gap the whole chain sits on top of.** `docs/index.html`'s click handler
   (`select_result` event) currently sends `item:` as the row's *display
   text* (`a.textContent.trim()`), not a stable id:
   ```js
   ga('select_result',{tab:entity,rank:rank,item:item});
   ```
   The board's row HTML (`render_board.py`) carries no `data-id` attribute,
   and `tags.json`/`latest.json` will be keyed by `entity_id`/`canonical_repo`
   — a stable slug, not display text (which can collide, get truncated, or
   differ from the slug for HN/Reddit-sourced titles). Joining clicks to tags
   by display-text string match would silently mis-join or drop rows. **This
   must be fixed before L2 pulls click data, and fixed as early as possible**
   because it requires registering one new GA4 custom dimension (`id`), which
   — like the existing 6 custom dimensions — takes ~24–48h to become
   queryable via `runReport`. Registering it in L1 instead of L2 buys back
   that lag time.
3. **`repos`/`rising`/`insiders` are views of the same repo entities, not
   separate entity types** (`entity_type` values are only `repo`/`paper`/
   `model`; `news` items are ungrouped headlines). One repo can appear in
   multiple tabs. Tags and click aggregates must key on `entity_id`, with
   `tab` carried as click *context* (useful for the referrer-diversity gate
   later), never as a second identity axis — otherwise the same repo tagged
   from the "rising" tab and the "repos" tab would silently fork into two
   click ledgers.
4. `categories.classify()` is currently called from exactly one place
   (`engine.py:386`, inside the repo scoring path) and is repo-only. Papers/
   models/news never get a category today.
5. `cli.py:_export()` (~line 731) is the single place that bakes
   `docs/index.html` and writes `docs/data/latest.json` — the natural hook
   for writing the new ledger files, since it already holds every entity's
   merged record (name, description, topics, entity_id) in memory.

## Ledger files (new, all under `docs/data/`, all small committed JSON)
`docs/` is already public (GitHub Pages) and `latest.json` already lives
there with no access control, so keeping the new files alongside it is
consistent — nothing in them is more sensitive than what's already public
(aggregated counts only, never a raw session id or IP).
- `tags.json` — `{entity_id: {tag, source: "keyword"|"exemplar-inferred"|"human-confirmed", confidence, updated_at}}`
- `embeddings.json` — `{entity_id: {vector, model, computed_at}}`, plus a `exemplars` map `{tag: [entity_id, ...]}` for confirmed anchors
- `exemplars_pending.json` — candidate exemplars awaiting Abe's one-line CLI approval
- `clicks.json` — `{entity_id: {tag, clicks: N, unique_sessions_seen: N, referrers: [domain,...], first_click_at, last_click_at}}` — rolling aggregates only, never raw per-click rows
- `patterns.json` — confirmed patterns + a labeled watchlist of near-misses

## Loops

### L0 — BASELINE (re-verify + scaffold)
`class: mechanical`
**goal:** Re-confirm the two baseline findings above at current HEAD, and
create the five ledger files with a minimal valid empty schema so every
later loop only appends.
**prompt:** Clone `github.com/abe238/hotinai` into an isolated scratch dir
(never the working tree Abe might have open). Re-run the concurrency check
against `.github/workflows/refresh.yml` at current HEAD and write the
verdict to `docs/evidence/l0-baseline/concurrency-audit.md` with the exact
block quoted. Re-check `docs/index.html`'s `select_result` handler and
confirm the `item:` param is still display-text (not a stable id) — quote
the current line. Create `docs/data/{tags,embeddings,exemplars_pending,clicks,patterns}.json`
each seeded with `{"_schema_version": 1}` plus their documented top-level
shape (empty dict/list per file). Do NOT wire these into `refresh.yml` yet.
**accept:**
- `docs/evidence/l0-baseline/concurrency-audit.md` exists, quotes the live
  `concurrency:` block, states "safe: queued, not concurrent"
- `docs/evidence/l0-baseline/join-key-audit.md` quotes the live
  `select_result` handler and states the gap
- All 5 files parse as valid JSON via `python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('docs/data/*.json')]"`
**bound:** 2
**exit →** L1

### L1 — JOIN-KEY FIX + all-entity tagging (`tags.json` goes live)
`class: feature`
**goal:** Fix the click→item join key, and extend deterministic tagging to
every entity type so `tags.json` starts accumulating real, correct data on
day one — the single biggest immediate-value, lowest-risk win in this chain.
**prompt:**
1. Add a stable id to each rendered row: `render_board.py`'s row `<div>`
   gains `data-id="{entity_id}"` (HTML-escaped); confirm every board.py
   `_row_from_*` function already carries `entity_id` through to the Row
   dict — if it doesn't for some entity type, thread it through rather than
   fabricating one.
2. Update `docs/index.html`'s click handler to also read
   `row.dataset.id`/`a.closest('.row').dataset.id` and send it as a new `id`
   param: `ga('select_result',{tab:entity,rank:rank,item:item,id:id});`.
3. Register `id` as a new GA4 custom dimension via the Admin API (same
   pattern as the 6 dimensions registered 2026-07-25 — see
   `~/.config/hotin-analytics/` scripts from that epoch for the exact call
   shape). This starts the ~24–48h processing-lag clock now, ahead of L2.
4. Extend `src/hotin/categories.py`: generalize `classify()` to accept an
   `entity_type` and a type-appropriate keyword set for `paper`/`model`/
   `news` (papers: task/functionality keywords per Abe's stated framing —
   "what you can do with it," not just weights; models: capability/tier
   keywords; news: what-changed keywords) — reuse the existing
   scoring/pattern-matching mechanism, don't reinvent it. Keep the repo
   category list unchanged (it already works).
5. In `cli.py:_export()`, after the board is baked, write `docs/data/tags.json`:
   every entity gets `{tag: classify(...), source: "keyword", confidence: 1.0, updated_at}`.
   Re-running classify on every bake is idempotent by construction (same
   input → same output), so no dedup logic is needed yet — pure overwrite
   per entity_id each run.
6. Wire this write into `refresh.yml`'s existing commit step
   (`git add docs/index.html docs/data/latest.json` → also add
   `docs/data/tags.json`).
**accept:**
- `docs/index.html` click handler sends `id` matching the clicked row's
  `entity_id`, verified live: open hotin.ai, click a repo row, confirm via
  `mcp__claude-in-chrome__read_network_requests` (or GA4 DebugView) that the
  outgoing `select_result` hit carries a non-empty `id` param equal to that
  row's `data-id`
- GA4 Admin API confirms `id` registered as a custom dimension (list call,
  not just "the create call returned 200")
- `hotin export` run locally against a small fixture produces a
  `docs/data/tags.json` with a non-"uncategorized" tag for at least one
  paper, one model, and one news item (PIN test: the fake-success mode here
  is "classify() runs but every non-repo item silently falls through to
  uncategorized" — assert against that explicitly)
- Live: next scheduled `refresh.yml` run (or a manual `workflow_dispatch`)
  commits an updated `docs/data/tags.json` at HEAD
**bound:** 2
**exit →** L2

### L2 — CLICK ACCUMULATION (`clicks.json` goes live)
`class: feature`
**goal:** Pull click/session data from GA4 and fold it into a permanent,
small, rolling aggregate — honest about the registration lag from L1.
**prompt:** Reuse the OAuth refresh-token GA4 auth pattern from
`~/.config/hotin-analytics/insights.py` (read `refresh_token` from
`~/.config/gcloud/application_default_credentials.json` + client id/secret
from `~/.config/hotin-analytics/oauth_client.json`, POST to
`https://oauth2.googleapis.com/token`, use the returned `access_token` —
never the `gcloud ... print-access-token` CLI path, it truncates when
piped). Add a step to `refresh.yml` (or a small script it calls) that:
1. Queries `runReport` for `select_result`/`star_click`/`copy_install`
   events with the `id`/`tab`/`rank` custom dimensions, filtered to the last
   ~3 days (covers the lag window with overlap).
2. **Two-pass, not one:** if `id` breakdown rows come back empty (still
   inside the 24–48h registration lag), write a `BREAKDOWN_PENDING` sentinel
   for this run — same honest pattern `insights.py` already uses — and do
   NOT fabricate zeros. The following run naturally retries.
3. For every real row, join `id` → `entity_id` against `tags.json` to get
   the item's current tag, then fold into `clicks.json`'s rolling aggregate:
   increment `clicks`, add the session to a *bounded* unique-session counter
   (a capped approximate count, e.g. a small HyperLogLog-free rolling
   window — exact uniqueness isn't load-bearing here, "roughly how many
   distinct sessions" is), append any new referrer domain, update
   `last_click_at`. Never store a raw per-click row or a raw session id —
   aggregate-only, by construction, not by redaction after the fact.
**accept:**
- `docs/evidence/l2-clicks/live-pull.md` shows one real (or honestly-pending)
  `runReport` response against the live GA4 property
- `clicks.json` at HEAD has non-zero `clicks` for at least the items Abe
  personally clicked while testing L1 (a concrete, checkable trace, not a
  structural assertion)
- PIN test: a fixture run with a still-registering `id` dimension produces
  `BREAKDOWN_PENDING`, not a silently-empty or silently-zero `clicks.json`
  (this is the exact false-success mode the L0 join-key gap made possible —
  guard it explicitly)
**bound:** 2
**exit →** L3 (human gate — see below)

### L3 — EXEMPLAR PROPAGATION (`embeddings.json`, inferred tags) — HUMAN GATE BEFORE LIVE
`class: gnarly`
**goal:** Move tagging beyond keyword-matching: one hand-confirmed exemplar
propagates its tag to embedding-similar items, with the guardrails the
ideate run's trap-adjudication attached (this mechanism is irreversible by
design — a bad exemplar's mistake compounds — so it does not go live
without an explicit Abe sign-off after the tracer-bullet proves the
embedding space actually clusters on the right dimension).
**prompt:**
1. **Tracer first, per the ideate deepen's own first-step:** compute
   embeddings (one hosted API call per new item, or local if cheap enough)
   for the current corpus as a **read-only artifact only** — write
   `embeddings.json`, do NOT write any propagation logic yet. Manually
   inspect nearest-neighbors for 3–4 hand-picked items per category to
   confirm the embedding space clusters on the *editorial* dimension
   (agent-orchestration vs not) and not just surface topic words. Report
   this to Abe as evidence before writing a single line of propagation code.
2. Exemplar candidates surface when an item crosses a strong click/dwell
   threshold (reuse `clicks.json`'s aggregate) — write candidates to
   `exemplars_pending.json`. **No inbound webhook, no new server:** notify
   Abe via the existing send-only Telegram pattern (Hermes bot creds) with
   the exact CLI command to approve (`hotin approve-exemplar <entity_id> <tag>`),
   which he runs locally; the approval commits `embeddings.json`'s
   `exemplars` map. This keeps the zero-new-infrastructure property (no
   inbound bot needed) at the cost of one manual step per new exemplar —
   an explicit, deliberate trade, not an oversight.
3. Propagation: every run, cosine-match untagged items against confirmed
   exemplars; matches above threshold write `tags.json` entries with
   `source: "exemplar-inferred"`. Guardrails (all four required, per the
   ideate deepen's rescue children — none optional):
   - **one-hop cap:** an inferred tag can never itself become an exemplar
     anchor for further propagation
   - **multi-exemplar consensus:** the match must be closer to this tag's
     exemplars than to any conflicting tag's
   - **re-verification loop:** inferred tags periodically rejoin the
     `exemplars_pending.json` queue for a human spot-check
   - **git-diff rollback:** because every write is a normal git commit,
     reverting a bad exemplar's whole cascade is `git revert` on its commit
     — document this procedure in `chain/`, don't build tooling for it
**accept:**
- Tracer evidence (nearest-neighbor inspection) reviewed and approved by
  Abe **before** any propagation code is written — this is a named human
  gate, not a checkpoint formality
- `tags.json` entries with `source: "exemplar-inferred"` exist at HEAD,
  each traceable to a specific confirmed exemplar in `embeddings.json`
- PIN test: an item whose best match is an *inferred* (not confirmed) tag
  does NOT propagate further (one-hop cap enforced, not just documented)
**bound:** 3 (this is the gnarly loop; more room before honest escalation)
**exit →** L4

### L4 — STATISTICAL FLOOR (`patterns.json`) — HUMAN GATE BEFORE LIVE
`class: feature`
**goal:** A weekly job that decides which tags have earned the right to be
called a "pattern" — the trust guardrail nothing downstream (least of all a
future newsletter) is allowed to bypass.
**prompt:** New weekly GitHub Actions workflow (separate from the 3h
`refresh.yml` — this reads `clicks.json`/`tags.json`, it doesn't refresh the
board). A tag becomes a named pattern only when ≥3 distinct `entity_id`s
each individually clear ≥3 unique-session clicks, within a rolling 7-day
window spanning ≥2 of `refresh.yml`'s bakes, **and** spanning ≥2 distinct
referrer domains across those items (the referrer-diversity gate — stops one
HN post driving clicks on 3 items from faking "independent" corroboration).
Near-misses (2 of 3 conditions met) go to `patterns.json`'s `watchlist` with
their raw counts shown, explicitly labeled, never phrased as confirmed.
**accept:**
- `docs/evidence/l4-floor/dry-run.md`: running the floor logic against the
  real `clicks.json`/`tags.json` accumulated by this point in the chain
  produces a `patterns.json` whose `confirmed` list (if any) is manually
  checked against the raw click data by Abe and found honest — this is the
  named human gate for L4
- PIN test: a synthetic single-referrer burst (3 clicks on 3 items, one
  domain) does NOT produce a confirmed pattern — the referrer-diversity
  gate is exercised, not just present in code
**bound:** 2
**exit →** L5

### L5 — RE-PLAN GATE (human gate)
`class: n/a — human gate`
**goal:** Review the accumulated evidence across L0–L4, confirm the full
loop (tag → click → propagate → gate) is producing honest, checkable output
on live data, and decide with Abe whether the newsletter draft generator
(design step 5, deferred from this chain's scope) becomes the next chain now
or later.
**accept:** n/a (human gate — waits unbounded by design)
**bound:** n/a
**exit →** successor chain doc (not an edit to this one), if Abe greenlights step 5

## Chain invariants (inherited from the cascade skill, restated for this chain)
- No loop advances without its EXIT.md (criterion → evidence pointer,
  verified at HEAD, never a commit message).
- Every ledger write in `refresh.yml` rides the existing `concurrency:
  hotin-refresh` group — never a second workflow racing the same files.
- Aggregate-only click storage is a hard rule, not a style preference — no
  loop may commit a raw per-click row or session id, ever.
- `docs/dashboard.html` stays where it is (already live, `noindex`), out of
  this chain's scope, untouched by any of L0–L5.
