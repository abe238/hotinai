# hotin — Full-Rigor Architecture (DEFERRED target)

**Status:** DEFERRED. We are building the **lean-correct** subset (see
`LOOP_CHAIN_EVOLUTION_2026-07-20.md`). This document is the full-rigor target
Sol reviewed us toward — the version to graduate to when hotin outgrows "simple
CLI" and the extra correctness/scale machinery earns its complexity.

> If someone asks "where is the full-rigor plan?" — it's this file:
> `chain/FULL_RIGOR_ARCHITECTURE.md` (also indexed in auto-memory
> `ref_hotin_full_rigor_plan.md`).

Source: Sol (codex) architecture review of the Cascades 1-3 plan, 2026-07-20.
Verdict: "Do not approve the plan as written. Cascade 1 is mostly sound, but
Cascades 2-3 rest on an incomplete identity model and an underspecified temporal
model."

## The target architecture (Sol's core)
- **One canonical record identity: `(entity_type, entity_id)`.** URL is
  provenance/presentation, never identity. `canonical_repo` retained only as a
  repo compatibility alias (for repos, `entity_id == canonical_repo`).
- **One latest-value cache keyed by `(entity_type, entity_id, source)`.**
- **Type-specific normalization, scoring, and rendering**; unify identity and
  grouping, not all domain behavior.
- **`merge_by_repo` retained as a repo-filtered compatibility interface** over
  shared grouping logic.
- **A separate ingestion-run / observation model** that distinguishes: missing
  history, source failure, unchanged metrics, and stale evidence.

## The 10 findings + their full-rigor fixes
1. **entity_type alone is not an entity model.** Persist `entity_id` (adapter id
   is currently dropped by `_normalise_record`, cache.py:22). Overloading
   `canonical_repo` is unsafe: `canonicalize()` accepts bare `org/name`
   (canonical.py:23), so `org/model` leaks as a repo. Use
   `UNIQUE(entity_type, entity_id, source)`.
2. **"hot stays repo-only" is false for a mixed cache.** `merge_by_repo()`
   (engine.py:167) canonicalizes every row; `hot/search/show` pass the whole
   cache in (cli.py). Filter by entity_type. Acceptance: seed repo+paper+model
   rows, prove hot/search/show/TTL/health/text/JSON stay repo-only.
3. **The cache is not a current snapshot.** Rows never expire → corroboration =
   "mentioned at any time," not simultaneous momentum. Add: `ingestion_runs`
   (start/completion/status/coverage), `last_seen_at` / source-specific expiry,
   explicit source-failure-vs-successful-absence, and corroboration computed
   only from evidence active within a window. Do NOT reuse repo-activity
   freshness for source-evidence freshness — different concepts.
4. **Scheduled ingestion can't use the best-effort cache.** It silently falls to
   memory and commits per-upsert. Needs a strict persistence mode + one batch
   transaction; persistence failure → nonzero exit. Pick ONE authoritative
   deployment (prefer single-writer local/VPS SQLite). If GitHub Actions: specify
   data path, concurrency group, checkpoint/close, retry, protected-branch perms,
   conflict handling. The default DB is under XDG, outside the repo — committing a
   WAL-mode binary SQLite is a mess.
5. **user_version migration is incomplete.** Both shipped and legacy `UNIQUE(url)`
   schemas may be user_version=0; adding a column leaves the bad constraint →
   silent memory fallback. Recreating `tools` invalidates FTS rowids (init skips
   backfill if tools_fts exists, cache.py:101). Install a linear transactional
   migration module: inspect physical schema → rebuild when columns/uniqueness
   differ → copy+dedup rows → drop/recreate+backfill FTS → validate → set
   user_version only on success → refuse/degrade on a newer DB. Test matrix:
   fresh, legacy UNIQUE(url), shipped UNIQUE(url,source), FTS present/absent,
   rollback after injected failure, idempotent reopen, SQLite-unavailable.
6. **Observation schema can't support idempotence or valid derivatives.** Needs
   run identity + uniqueness (e.g. `(run_id, entity_type, entity_id, source,
   subject_id, metric)`). Not all metrics are differentiable: stars/downloads may
   be cumulative, npm_downloads_week is a rolling gauge, npm_growth is already a
   derivative, HN/Reddit points may refer to a different winning post next
   ingest, YouTube views can switch videos, trending scores/ranks reset. Add a
   **metric registry**: kind, unit, subject identity, monotonicity, reset policy,
   min interval, transformation, caps. Require 2 well-spaced samples for velocity,
   3 for acceleration.
7. **Velocity composed outside the snapshot scorer.** Keep pure snapshot as
   `base_score`; compute temporal features in a separate module; compose. No
   history → total==base exactly. Insufficient → velocity_state="unknown", not
   zero. Don't fold velocity into freshness_factor. Keep a separate `rising`
   ranking; changing default `hot` order is an explicit product decision.
8. **HF/smol loops have no clean scoring/persistence path.** score_repo gets one
   merged repo; rank() gives no paper/model context (engine.py:203). fetch_all
   persists only result["records"] — a separate smol digest payload is ignored
   (engine.py:117), so the offline brief has no event source. Represent
   cross-entity links explicitly (typed links); build a `repo_id ->
   cross_entity_evidence` index before ranking; store news/topic in an
   event/evidence table or a 4th topic/news entity; expire bridge evidence with
   the source snapshot. A `source="smolai"` record auto-increments source_count
   and multiplies score by 1.25 before any "light" boost — flag-only evidence
   must NOT enter the independent-source set.
9. **Flat merge loses provenance.** `signal.update()`/`meta.update()`
   (engine.py:194) are order-dependent. Make `signal_by_source` + `meta_by_source`
   authoritative; keep flattened repo fields for compatibility; define aggregation
   for booleans/counters/links/titles/conflicts.
10. **Adapter-invariant enforcement gaps:** load_config only overlays env for keys
    already in .env (config.py:46) → env-only YOUTUBE_API_KEY/HOTIN_YT_CHANNELS/LLM
    keys don't work; per-instance Throttle isn't host-global (HF papers+models can
    hammer huggingface.co together); YouTube needs a quota budget not just sleeps;
    secrets asserted absent from URLs/logs; HF HTML/JSON schema change must produce
    `error` not believable `empty`; smol malformed-XML test needs namespaces, CDATA,
    escaped HTML, multiple malformed items, size bounds; optional LLM stays
    stdlib-only via urllib (no SDK), with timeout/throttle/bound/deterministic
    fallback.

## Sol's answers to the 4 open questions
1. **Entity model:** adopt unified `(entity_type, entity_id)` now; keep
   `merge_by_repo` as compat; type-specific scorers/renderers.
2. **Curated-channel weighting:** NOT corroboration, NOT a source. One credibility
   feature regardless of channel/video count. Cap ~5% of pre-bonus score AND an
   absolute 1 point, whichever is smaller — well below the 25% independent-source
   increment.
3. **Sparse-history velocity:** unknown = neutral. Preserve snapshot exactly, no
   rising/viral badge, expose "collecting history." 2 valid samples for velocity,
   3 for acceleration. New entrants still rank via snapshot strength.
4. **Brief determinism vs richness:** deterministic brief MUST be the product
   (ranked deltas, new entrants, cross-entity links, source coverage, explicit
   traceable facts). LLM = opt-in renderer over immutable fact records, never the
   calculator. If the brief isn't useful without an LLM, the offline premise is
   false and must be changed explicitly.

## What lean-correct keeps vs defers
- **Keeps (correctness-critical):** `(entity_type, entity_id)` identity; hot
  entity-filtering; no smol double-count (flag-only, not a source); real
  transactional migration; a light `last_seen_at`/evidence-window for
  corroboration; metric-kind awareness (differentiable vs gauge vs already-a-rate);
  velocity composed outside the snapshot scorer; the 2 shipped-bug fixes.
- **Defers to this doc:** full `ingestion_runs` model + coverage state; the full
  metric registry; cross-entity link + event tables as first-class schema; strict
  multi-mode persistence with the full deployment spec; the exhaustive per-loop
  test matrices. Revisit when scale/service ambitions justify them.
