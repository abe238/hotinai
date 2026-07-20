# hotin Evolution — Cascades 1-3

**Goal:** take hotin from a shipped snapshot repo tool (v0.1.0) to a continuous,
multi-entity AI situational-awareness system: **repos** (build), **papers** (read),
**models** (run), **brief** (what happened) — ranked by cross-source corroboration
and, ultimately, velocity.

**Pacing:** checkpointed at each cascade boundary. Within a cascade, autonomous.
Each cascade ends with test → simplify → verify → code-review before the next.

## Lean-correct revision (per Sol review, 2026-07-20)

Sol reviewed this plan and correctly flagged that the entity + temporal models
were too shallow. We build the **lean-correct subset**; the deferred full-rigor
version is `chain/FULL_RIGOR_ARCHITECTURE.md`. Binding adjustments:

- **Loop 2A uses `(entity_type, entity_id)`, not just a type column.** For repos,
  `entity_id == canonical_repo`. Cache key becomes
  `UNIQUE(entity_type, entity_id, source)`. URL is provenance, never identity
  (a bare `org/model` would otherwise canonicalize as a repo and leak into hot).
- **hot/search/show FILTER to `entity_type == "repo"`** before merge_by_repo.
  Acceptance seeds a mixed repo+paper+model cache and proves the repo views stay
  repo-only (health.summarize included).
- **smol is flag-only, NOT a source.** A `source="smolai"` record must not enter
  the independent-source set (it would auto-multiply score by 1.25). Its repo
  mentions are a bounded credibility flag, capped like curated channels.
- **Curated channels (Loop 1B): a credibility feature, not corroboration.** Cap
  at min(5% of pre-bonus score, 1.0 absolute), well below the 25% source
  increment. Do NOT add a synthetic source or increment source_count.
- **Cache migration (Loop 2A) is a real transactional migration**, not just an
  added column: detect the legacy `UNIQUE(url)` and shipped `UNIQUE(url,source)`
  physical schemas (both user_version=0), rebuild `tools` + dedup + FTS backfill,
  set user_version only on success, refuse a newer DB.
- **Velocity (Loop 3C) is composed OUTSIDE the snapshot scorer.** base_score
  stays pure; no history → total == base exactly; insufficient history →
  velocity_state="unknown" (neutral), no rising/viral badge; 2 samples for
  velocity, 3 for acceleration. Keep a separate `rising` view; changing default
  hot order is a deliberate product decision, not a side effect. Metric-kind
  awareness (cumulative vs gauge vs already-a-rate) before differencing.
- **Scheduled ingest (Loop 3B) needs strict persistence** (one batch txn,
  nonzero exit on failure, no silent memory fallback) and ONE authoritative
  deployment (prefer single-writer VPS/local SQLite over committing a WAL binary
  to git).
- **Brief (Loop 3D) deterministic is the product**; LLM is an opt-in renderer
  over immutable, traceable fact records via urllib (no SDK), never the calculator.
- **DONE already (shipped-bug fixes, commit 8351855):** env-only known keys are
  now read from the environment; corroboration now uses a 21-day evidence window
  (EVIDENCE_WINDOW_DAYS) so stale mentions drop out of hot/search.
- **Throttle is per-instance, not host-global:** HF papers + models share
  huggingface.co, so they must share one throttle (or one HF client).

## Invariants (repo_notes — every executor must honor these)

1. **Best-effort adapter contract.** Every `fetch(query, limit, config)` returns
   `{"records": [...], "status": "ok"|"empty"|"error", "detail": str|None}` and
   NEVER raises. Wrap the whole body in `except Exception`.
2. **Stdlib-only runtime.** Zero third-party runtime dependencies. `urllib`,
   `sqlite3`, `json`, `re`, `xml.etree`, `argparse` only. (Optional key-gated LLM
   enrichment in Cascade 3 is the sole, explicitly-optional exception, and must
   degrade cleanly to the deterministic path when absent.)
3. **Be kind to servers.** Every outbound request goes through a `Throttle`. No
   un-throttled path, no retry storms, bounded per-source request counts. Sources
   can lock down at any time; assume it and degrade gracefully.
4. **Secrets via config/env only** (`~/.config/hotin/.env` or the process env),
   never committed, never logged, never in a URL.
5. **Terminal-safe rendering.** Untrusted text routes through `render.sanitize()`;
   color/hyperlink only when `enabled` (tty and not `--no-color`).
6. **Cache schema is versioned/migrated.** (Learned the hard way: a pre-release
   dev cache with the old `url UNIQUE` schema silently fell back to memory because
   `CREATE TABLE IF NOT EXISTS` never migrates. Any schema change from here MUST
   detect an out-of-date table and migrate/recreate, or bump a `PRAGMA user_version`
   and rebuild.)
7. **Additive, not destructive.** The shipped repo pipeline (v0.1.0) is battle-
   tested. New entities and sources are added alongside it; the repo path is not
   refactored unless a loop's accept criteria explicitly require it.

---

## Cascade 1 — Repo-source expansion (repo entity, low risk)

More high-yield repo signal. No engine or schema change. Empirically, smol.ai is
NOT here (28 repos vs 1030 Twitter mentions across the whole feed — it's a
model/news signal, moved to Cascade 2).

### Loop 1A — YouTube Data API v3 backend
`goal`: youtube adapter prefers the official YouTube Data API v3 when
`YOUTUBE_API_KEY` is configured, falling back to ScrapeCreators otherwise.
`prompt`: In `sources/youtube.py`, add an official-API path: `search.list`
(part=snippet, type=video, order relevance/date, the existing DEFAULT_QUERIES)
to get video IDs, then `videos.list(part=snippet,statistics)` for full
descriptions + `viewCount`. Extract GitHub repos from the full description
(reuse `canonical.GITHUB_URL_IN_TEXT_RE` + `trim_glued_repo_name`). Key from
`config["YOUTUBE_API_KEY"]`. If absent, use the existing ScrapeCreators path
unchanged. Both paths throttled. Contract unchanged.
`accept`: unit tests (fixture) for the v3 parse (search+videos join, missing
description, hostile values); live smoke with a real key returns records; no-key
path still uses ScrapeCreators; `pyflakes` clean; adapter never raises.
`bound`: 2 PROVE rounds.

### Loop 1B — Curated high-signal channels
`goal`: harvest repos from a configurable shortlist of curator channels
(ManuAGI, GithubAwesome, AI Motion Studio, ...), which put 20-35 repos in each
video description; a repo surfaced by a curator earns a corroboration boost.
`prompt`: Add a channels mode: fetch each configured channel's recent uploads
(YouTube v3 `playlistItems` on the uploads playlist, or ScrapeCreators channel
endpoint), pull full descriptions, extract repos. Ship a DEFAULT set of channel
handles/IDs, overridable via config (`HOTIN_YT_CHANNELS`). Emit a meta flag
(e.g. `youtube_curated: true`) so the engine can give curator-surfaced repos a
small credibility/corroboration nudge (do NOT double-count the same repo as
multiple sources). Bound requests (cap channels × recent-videos). Throttled.
`accept`: fixture tests for channel-uploads parse + repo extraction; the
curated meta flag flows into scoring with a bounded, documented weight; live
smoke yields real curated repos; empirical channel shortlist recorded (ranked
by resolvable-repos-per-video, not memory); contract holds.
`bound`: 2 PROVE rounds.

`exit →` Cascade 1 gate: test/simplify/verify/code-review, then Cascade 2.

---

## Cascade 2 — Entity model + papers/models/news (architectural)

The one architectural cascade. **Sol reviews the entity-model design before build.**

### Loop 2A — Light entity_type model (Sol-gated design)
`goal`: introduce `entity_type` (repo | paper | model) without disturbing the
shipped repo path.
`prompt`: Design options (Sol to weigh in): (a) add an `entity_type` column to
the cache (default "repo", migrated per invariant 6) + carry it on records;
(b) generalize `canonical_repo` -> a type-aware `entity_id` while keeping a
`canonical_repo` alias for repos; (c) keep merge_by_repo for repos and add
parallel `merge_by_entity` for papers/models. Recommended: (a)+(c) — smallest
blast radius, repo engine untouched, papers/models get their own merge+score+
render. `hot` stays repo-only. Include the cache migration (bump
`user_version`, add column or recreate).
`accept`: schema migration proven (an old-schema cache is upgraded, not dropped
to memory); repo path byte-for-byte behavior-preserved (existing 167 tests
green); entity_type round-trips through cache; Sol's design findings resolved.
`bound`: 3 REVIEW rounds (design-sensitive).

### Loop 2B — HF papers adapter (`hotin papers`)
`goal`: trending papers as a paper entity.
`prompt`: `sources/hfpapers.py` — fetch https://huggingface.co/papers (the
daily trending list; parse the embedded JSON/HTML defensively). Entity: paper,
id = arxiv id (or HF paper slug), metrics = upvotes; meta = title, authors,
arxiv url, any linked github repo / HF models. New `hotin papers` command with
paper-appropriate columns (upvotes, title, authors, arxiv link). Never raises,
throttled, stdlib-only.
`accept`: fixture parse tests (valid + malformed + hostile); `hotin papers`
renders a real trending list live; contract holds.
`bound`: 2.

### Loop 2C — HF models adapter (`hotin models`)
`goal`: trending/new models as a model entity.
`prompt`: `sources/hfmodels.py` — fetch trending models
(https://huggingface.co/models?sort=trending, or the HF API
`/api/models?sort=trendingScore`). Entity: model, id = org/model, metrics =
downloads + likes; meta = task/pipeline_tag, base model, linked paper/repo.
New `hotin models` command. Defensive parse, throttled, stdlib-only.
`accept`: fixture tests; `hotin models` renders live; contract holds.
`bound`: 2.

### Loop 2D — smol.ai as a model/news signal + light repo corroboration
`goal`: mine smol.ai/AINews for (i) trending models/topics (feeds Cascade 3
brief) and (ii) the ~28 repos it editorially mentions (a light corroboration
boost, NOT a standalone repo source).
`prompt`: `sources/smolai.py` — fetch the RSS, parse DEFENSIVELY against the
intermittent XML typo: try `ET.fromstring`; on ParseError, fall back to a
tolerant per-`<item>` regex extractor that skips only the malformed item, not
the whole feed. From `content:encoded` extract: github repos (corroboration
signal), model/HF mentions and topic phrases (a compact structured "what
mattered" payload for the brief). Emit repo records with a `smol_mention` meta
flag (light corroboration, bounded weight, no double-count) and a separate
digest payload for the brief. Attribution: we synthesize our own view; we do
NOT re-serve smol's prose.
`accept`: defensive-parse test proves a deliberately-malformed feed still yields
the good items; repo corroboration flag flows with bounded weight; digest
payload shape is stable; contract holds.
`bound`: 2.

### Loop 2E — Cross-entity bridge
`goal`: a repo that is the implementation of a trending paper/model earns a
corroboration boost (the real cross-entity value, without a graph engine).
`prompt`: when a paper/model record carries a linked github repo, record that
link; in scoring, give a repo a bounded boost if it is linked from a trending
paper or model. One-directional, bounded, documented.
`accept`: test proves a repo linked from a high-upvote paper outranks an
identical repo without that link; boost is bounded and cannot dominate
corroborated momentum.
`bound`: 2.

`exit →` Cascade 2 gate: test/simplify/verify/code-review, then Cascade 3.

---

## Cascade 3 — Velocity + continuous freshness + brief

The snapshot → movie arc. Answers "how do we see virality without running the
CLI constantly."

### Loop 3A — Append-only observation store
`goal`: keep history so velocity is computable.
`prompt`: add `observations(entity_type, entity_id, source, metric, value,
observed_at)` append-only table (migrated per invariant 6). The existing cache
stays the latest-value store; observations accumulate the time series. Bounded
retention (prune > N days) like Impact Signals' accumulator.
`accept`: two ingests of the same entity produce two observations; retention
prune works; no impact on the existing snapshot path.
`bound`: 2.

### Loop 3B — `hotin ingest` + scheduled runner
`goal`: a server, not a human, keeps the store fresh.
`prompt`: `hotin ingest` = fetch all sources and APPEND observations, idempotent
and cron-safe (exits cleanly, os._exit like hot). Add a GitHub Actions cron
workflow (hotin already has a scheduled live-smoke pattern) that runs `hotin
ingest` every N minutes/hours and commits/pushes the data (or documents the
VPS-cron / Cloudflare-cron alternatives). Throttled; be kind to servers is
EASIER here (one controlled fetcher vs many live users).
`accept`: `hotin ingest` appends and exits fast; the scheduled workflow runs
green on a schedule and grows the store; documented rate posture.
`bound`: 2.

### Loop 3C — Velocity + acceleration scoring
`goal`: rising/viral = derivatives, not a snapshot.
`prompt`: from the observation time series compute velocity (d(metric)/dt) and
acceleration (d(velocity)/dt) per entity. Add a "rising"/"viral" signal = high
velocity AND positive acceleration AND cross-source corroboration, recency-
weighted. Freshness gains a velocity dimension. Repo engine's snapshot score
stays; velocity is additive.
`accept`: a repo with a rising star time series outranks an identical repo that
is flat at the same absolute level; the C0-RADAR-style `rising` view works;
snapshot-only users (no history yet) still get a sane score.
`bound`: 3.

### Loop 3D — `hotin brief`
`goal`: the human-readable payoff — "what happened today."
`prompt`: `hotin brief` = a short deterministic daily digest computed from the
store's deltas across all entity types ("N repos crossed X stars, model Y
dropped, paper Z surging, topic W trending per AINews"). Stdlib-only, honest,
offline-capable. OPTIONAL: if an LLM API key is configured, enrich into prose;
absent the key, the deterministic digest is the product (never required).
`accept`: `hotin brief` renders a coherent deterministic digest from real store
data with zero third-party deps; the optional LLM path degrades cleanly to
deterministic when no key; nothing fabricated (every line traces to a delta).
`bound`: 2.

`exit →` Final gate: test/simplify/verify/code-review; re-do the HTML showcase
with all new real data (Track C); present a release-readiness verdict (v0.2.0)
at a human gate. No publish/announce without explicit go.

---

## Ordering & parallelism
- Cascades are sequential (1 → 2 → 3), each gated by test/simplify/verify/code-review.
- Within Cascade 1: 1A then 1B (1B builds on the v3 backend).
- Within Cascade 2: 2A first (design, Sol-gated), then 2B/2C/2D in parallel,
  then 2E (needs paper/model links).
- Within Cascade 3: 3A → 3B → 3C → 3D (each builds on the prior).

## Open design questions for review (Fable + Sol)
1. Entity model: is (a column + parallel merge_by_entity) the right minimal shape,
   or does a unified `entity_id` pay off? (Sol, Loop 2A.)
2. Curated-channel weighting: how much boost without letting a single curator
   dominate corroborated cross-source signal?
3. Velocity with sparse history: cold-start behavior before the store has depth
   (Loop 3C) — how to avoid penalizing everything as "no velocity."
4. Brief determinism vs. richness: is the deterministic digest genuinely useful
   without the LLM, or is the LLM path the real product (and thus a soft dep)?
