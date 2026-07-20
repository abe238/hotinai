# LOOP CHAIN — `hotin` (what's hot in AI, from your terminal)
Pacing: **autonomous**, two human gates — (1) this plan [PASSED — Sol: GO-WITH-CHANGES, folded
in below], (2) before publishing/announcing a release (L5).
Executors: terra (codex) implements; **Sol (codex frontier) reviews the plan + every loop diff**.
Target repo: **github.com/abe238/hotinai** (already public, Apache-2.0 + NOTICE, `docs/` reserved
for the GitHub Pages site — CLI package lives at repo root). Live domain: **hotin.ai**.

## Mission
The fastest way to see **what's hot, fresh, and viral in AI — tools AND social — from your terminal.**
Zero setup for the core, works on any fresh machine, gets sharper the more you use it.

## Hard contract (verify at every loop)
- **Only hard dependency: Python 3.9+.** SQLite is bundled; **FTS5 may be absent on some
  Python/SQLite builds — code MUST detect this and fall back to a `LIKE`-based search path**,
  never crash or require a rebuild (Sol P2 fix #2).
- **SQLite-only. Zero database server. No Postgres, no pgvector — ever, as a requirement.**
- **No required external binaries.** the influencer-stars source smart-money is Python-only (no Go binary; the existing
  `insider-pp-cli` scrape pattern is reimplemented, not shelled out to).
- **Smart-money stays PRIMARY and heavily weighted (revised 2026-07-20 — do not re-demote this).**
  Sol's original "demote" language conflated two different things: RESILIENCE (the `hot` command
  must not depend on the influencer-stars source's uptime to run at all) and SIGNAL WEIGHT (how much a working smart-money
  read moves the score). Only the first is required. When the adapter succeeds, its contribution
  is NOT capped low — it's a primary term, same tier as momentum. When it fails, the engine
  degrades gracefully (score computes without it), it just never blocks the core `hot` command.
  **Architecture (superseded twice — read this, not the earlier "cache-usernames-then-check-via-
  GitHub-stargazers-API" idea, which is DEAD; GitHub restricted `/repos/{o}/{r}/stargazers` to
  admins/collaborators June 30 2026, confirmed live 404 on real repos):**
  - **Primary: the influencer-stars source's own repo-centric recent-activity feed** (`/ai/github/stars`, what
    `insider-pp-cli` already hits) — it already returns `most_recent_star_at` with real, hours-fresh
    timestamps (verified live: `2026-07-19T23:41:12Z` on a same-day check). This is repo-centric,
    naturally fresh, and the influencer-stars source has already done the account-tracking/identity-joining work — no
    reason to rebuild that ourselves.
  - **Harden it, don't replace it (per Sol's second review):** schema-drift detection (the parser
    must detect an unexpected shape and degrade to `[]` + a warning, never crash — this is the
    original P1 pattern already fixed once in the yt-tool-extraction sibling project, reuse that
    discipline), a freshness gate + 30-day retention with recency decay (old smart-money
    observations should fade, matching the engine's general freshness treatment), explicit source
    provenance + timestamp stored per observation, and **`unknown` outside the observed window
    rather than implying "confirmed zero smart-money interest."**
  - **REJECTED as the core mechanism, kept as the DISASTER-RECOVERY fallback (revised 2026-07-20
    per Abe: the influencer-stars source itself could also lose access, same as GitHub's stargazers endpoint did — treat
    that as a real, not hypothetical, failure mode; this fallback exists so smart-money doesn't
    go completely dark if the influencer-stars source's feed is ever cut off, not as a routine alternate path):**
    bulk-crawling each of the ~1,000 cached AI-1000 usernames' starred-repo history via GraphQL
    (`user(login:).starredRepositories`, confirmed technically live/cheap in raw API points).
    Sol's second review killed it as the PRIMARY path: harvesting people's full star history on a
    recurring cron is disproportionate to "did a credible person notice this recently," and
    shares the same abuse-pattern shape GitHub just restricted (mass collection of star
    relationship data), just inverted — a real risk of being closed next, and arguably not
    something to build the product's core on even if it stays open.
    **If ever activated (the influencer-stars source feed confirmed dead, not just one bad fetch), it MUST run as a slow
    trickle, never a burst — the whole point is to never be the reason another source locks down**:
    spread the full ~1,000-account refresh across **at least 24 hours**, a low fixed rate (e.g. a
    few accounts per minute with real jittered sleep between each, not "as fast as the point
    budget allows"), sequential per account (never parallelize this specific job), paginate only
    as many pages of a very prolific user's history as needed and stop early once reasonably
    covered rather than exhausting it, and cache+reuse partial progress across restarts so a
    trickle resumes where it left off instead of restarting the clock. This is explicitly the
    "be kind to servers" principle applied at its highest-risk point. Needs an explicit opt-out
    mechanism for tracked people if ever enabled.
  - **Cap smart-money's contribution relative to corroboration** — it's a heavily-weighted primary
    term, but corroboration (independent-source agreement) stays the strongest multiplier; smart-
    money alone should not be able to single-handedly outrank a repo with zero independent
    corroboration, per Sol's balance note.
- **Honest zero-key claim (Sol fix #2):** the **zero-key core** is GitHub + the public repo-trends API + HN + npm
  — this must be excellent with NO configuration. Reddit + YouTube are **key-unlocked social**
  (ScrapeCreators) and are documented as such, never blurred into "zero setup covers everything."
- **No telemetry, ever** — not even anonymous/opt-in. (Standing decision, not up for silent
  reversal later.)
- **Be kind to servers — standing engineering principle, applies to every adapter (added
  2026-07-20 per Abe: the influencer-stars source itself could get rate-limited or cut off, same as GitHub's stargazers
  endpoint was; assume every unofficial or informally-generous source can tighten at any time,
  and never be the reason it does).** Every adapter uses the shared `throttle.py` primitive built
  in L0: a minimum interval between requests to the same host (with jitter, never a tight loop),
  real respect for `Retry-After`/`X-RateLimit-*` response headers (back off further than asked
  when in doubt, never race a limit), and conditional requests (ETag/If-None-Match) where a
  source supports them. Concurrency across DIFFERENT sources is fine (L2's concurrent fetch), but
  a single source is never hammered just because its documented limit technically allows it —
  technically-allowed and considerate are not the same bar. Any bulk/many-request job (e.g. the
  smartmoney-deep fallback below) runs as a **slow trickle spread over hours, not a burst** —
  see that section for the concrete cadence.
- **Per-source failure isolation, not "never crashes" (Sol fix #9):** a source failing emits `[]`
  and a structured status, never raises. But if EVERY source fails AND no local cache exists,
  the CLI exits **nonzero** with a concise health summary — it does not print an empty, cheerful
  board and pretend that's success. Partial success (≥1 source ok) exits 0 with per-source status
  visible in `--verbose`/`--json`.
- **Sanitize all untrusted rendered text (Sol fix #3):** repo descriptions, HN titles, usernames,
  URLs can carry ANSI escapes, control chars, OSC hyperlinks, bidi overrides. Strip/escape before
  ever writing to the terminal. A hostile-fixture test (malicious description with embedded
  escape codes) is part of the L1/L3 test suite, not optional.
- **Key handling hardened (Sol fix #4):** config dir created with private perms; atomic writes
  (write temp + rename); refuse to follow a symlink at the key-file path; never put a token in a
  URL or in argv passed to a subprocess; if shelling to `gh`, use an argv list, never a shell
  string. `~/.config/hotin/.env` (or platform equivalent), gitignored, mode 600.
- **Cache failure is non-fatal (Sol fix #5):** SQLite locked/corrupt/unwritable → catch it, warn
  once, still render live-fetched results for this run. Never let a cache write failure abort
  the whole command.
- **CI split (Sol fix #6):** fixture/parser/contract tests run in the blocking CI (fast,
  deterministic, no network). A separate **scheduled** workflow does live-source smoke checks and
  reports source health — it never blocks a PR or release.
- **Canonicalize before corroborating (Sol fix #7):** normalize `.git` suffix, case, redirects,
  npm-monorepo subpaths, and renamed repos to a single canonical `owner/repo` (or GitHub
  `node_id` when cheaply available) BEFORE two sources are compared for corroboration — otherwise
  corroboration/dedup silently undercounts.
- **Attribution footer, not growth-hacking (Sol fix #8):** shown on first run and on `hotin about`
  only — not on every invocation. `--quiet` suppresses it. NEVER printed when stdout is piped or
  when `--json` is used (machine consumers never see marketing text mixed into output).
- **Data-sources/terms section (Sol fix #10):** the license covers hotin's own code; it does not
  relicense the influencer-stars source/Reddit/YouTube/npm/GitHub data. README gets an explicit "Data Sources & Terms"
  section; cached third-party text (descriptions, titles) is minimized and TTL'd, not archived
  indefinitely; Reddit/YouTube adapters are labeled unofficial third-party integrations.

## The momentum reframe (fresh machine, zero accumulated history)
- **the public repo-trends API** `/trends/repos?period=past_week` → precomputed weekly star-growth. Zero-key core.
- **GitHub search** `created:>Nd sort:stars` → young-but-already-huge = implied velocity. Zero-key core.
- **npm** week-over-week download growth. Zero-key core.
- **HN** recency inside the window. Zero-key core.
- **Local `star_history` is an OPTIONAL precision bonus:** `hotin update` snapshots stars locally
  so momentum sharpens over repeated runs — a retention hook, never a requirement.
Corroboration/freshness/credibility/categories all compute at query time from live data — zero
history required (PROVE this at L2 by wiping the cache and re-running).

## Source adapters — uniform interface `fetch(query, opts) -> FetchResult`
`FetchResult = {records: list[Record], status: "ok"|"empty"|"error", detail: str|None}` — the
engine needs the status, not just an empty list, to build the health summary (Sol fix #9).
Normalized `Record`: `{url, canonical_repo, name, source, stars?, signal:{...}, meta:{...}}`.
Each adapter: stdlib-first, a `--selftest` with hostile-input fixtures, never raises.

**Zero-key core (must be excellent alone):**
1. **github** — search / stars / repo metadata. Token-optional (60→5000/hr).
2. **trends** — weekly/monthly star-growth trends. No key.
3. **hn** — Algolia `search_by_date` (10k req/hr documented allowance), points floor + window,
   github repos only, canonicalized. No key.
4. **npm** — registry search → repo link + download velocity. No key.

**Key-unlocked social (clearly optional, documented as such):**
5. **reddit** — ScrapeCreators `/v1/reddit/subreddit` + `/search`. No key → `[]`, never fatal.
6. **youtube** — ScrapeCreators `/v1/youtube/search`. No key → `[]`.

**Primary credibility signal (resilience-optional, weight-primary — see the full spec above):**
7. **smartmoney** — the influencer-stars source's repo-centric recent-GitHub-stars feed (`/ai/github/stars`), pure-Python
   scrape (reimplements the `insider-pp-cli` pattern, no external binary). Best-effort TRANSPORT
   (engine ranks correctly if this adapter is entirely absent/broken this run) but a PRIMARY,
   heavily-weighted signal when it succeeds — not demoted in importance. Includes schema-drift
   detection, a freshness gate + 30-day retention with decay, and `unknown`-outside-window
   semantics (never implies zero interest just because it's outside the observed range).

**Experimental, feature-flagged, OFF by default (not L1's dependency):**
8. **smartmoney-deep** — the GraphQL starred-repos-history inversion. Rejected as core (see spec
   above); implement only behind an explicit opt-in flag if built at all, never wired into the
   default `hot` ranking path.
9. **x** — stub only; ScrapeCreators doesn't cover X. Documented as bring-your-own-creds, not v1-core.

## The engine (query-time, no-history-required)
- **canonicalization** — first pass, before anything else touches a record (Sol fix #7).
- **corroboration** — distinct canonical sources; multiplier `1 + 0.25·(N−1)`.
- **freshness** — days since last activity; ≤30d=1.0 → 0.2 floor by 150d; resurgent counts fresh.
- **credibility** — smart-money term (log starrers + rank bonus), zero when adapter absent.
- **categories** — deterministic 6-core classifier (agents/app-building/dev-tools/inference/
  training/creative-media + uncategorized).
- **momentum** — the public repo-trends API/npm/young-popular (+ optional local history).
- **provenance-aware score** — `(momentum + credibility + signal) × corroboration × freshness`,
  and the per-source contribution to `signal`/`credibility` is retained per-record (not just the
  summed total) so `--verbose`/`--json` can show *why* a repo ranked where it did (Sol fix on
  "define provenance-aware normalized scoring").
- **concurrent, cache-first fetch (Sol's engine-spec gap):** adapters fetch in parallel
  (thread pool; stdlib `concurrent.futures`, no new dependency) with a per-adapter timeout; a
  fresh-enough cached result serves instead of a network call when within its TTL. This bounds
  `hotin hot` wall-clock to roughly the slowest single adapter's timeout, not the sum of all of them.

## CLI surface
- `hotin` / `hotin hot` — flagship ranked board (default).
- `hotin hn | npm | stars | trending | reddit | youtube` — single-source views.
- `hotin search <query>` — FTS5 (or LIKE fallback) over the local cache.
- `hotin show <owner/repo>` — one repo, all signals, provenance breakdown.
- `hotin setup` — configure keys + structured dependency/health check (`--check` for scripting).
- `hotin update` — refresh cache + snapshot stars (builds local momentum history).
- `hotin about` — ASCII banner + attribution + version.
- Flags: `--category`, `--fresh Nd`, `--language`, `--since Nd`, `--min-stars N`, `--source a,b`,
  `--limit N`, `--json`, `--no-color`, `--quiet`, `--verbose`.
- Exit codes: `0` full/partial success, `1` all sources failed + no cache, `2` bad usage.

## Attribution (subtle, never spammy)
- `github.com/abe238/hotinai`, Apache-2.0 + NOTICE.
- First-run + `hotin about` only: `◇ hotin · what's hot in AI · @abe238 · hotin.ai`.
- Never on piped stdout, never with `--json`, suppressible with `--quiet`.

## Loops
### L0 — FOUNDATION
goal: portable package skeleton, SQLite cache (WAL, FTS5-with-LIKE-fallback), config/key loader
(hardened per the key-handling contract), `setup --check`, canonicalization module, ANSI-safe
render helper, health-summary/exit-code contract.
accept: `hotin --help` lists all commands; `hotin setup --check` exits 0 with ZERO keys; cache
schema created idempotently; forcing FTS5-unavailable (mock) still returns search results via
LIKE; a hostile-string render test (ANSI/control chars) passes; stdlib-only, no network, selftest green.
bound: 2. exit → L1.

### L1 — SOURCE ADAPTERS (parallel: terra ×N, disjoint files per adapter)
goal: all 8 adapters behind the uniform interface; zero-key-core adapters excellent alone.
accept: each adapter returns real normalized+canonicalized records against the live API (or a
clean `FetchResult(status="empty")` when its key is absent) — a real fetch trace per adapter;
selftests include a fuzzed/hostile-input case that must NOT raise; reddit/youtube tested against
ScrapeCreators with a real (non-committed) key during dev, verified to degrade to `[]` with none.
bound: 2 per adapter. exit → L2.

### L2 — ENGINE
goal: canonicalization + corroboration + freshness + credibility + categories + provenance-aware
scoring + concurrent cache-first fetch; the `hot` command end-to-end.
accept: **wipe the local cache, `hotin hot --json` still ranks real live data** (no-history-
required, proven in a trace); corroboration correctly dedupes two URL variants of the same repo
(canonicalization proof); a wall-clock trace shows fetch is parallel, not serial; all-sources-
fail simulation exits nonzero with a health summary; partial-success exits 0.
bound: 3. exit → L3.

### L3 — CLI UX
goal: all subcommands + flags; beautiful ANSI-safe terminal render; attribution per the
never-spammy contract; `--json`/`--quiet`/`--verbose`; provenance shown in `show`/`--verbose`.
accept: every command runs against live data; a hostile repo-description fixture renders safely
(no escape leakage) in a real terminal capture; `--json` output has zero attribution/marketing
text and is valid parseable JSON; footer absent when piped (`hotin hot | cat` shows no footer).
bound: 2. exit → L4.

### L4 — DIST & DOCS
goal: packaging (pyproject.toml → pip/pipx/uv; a single-file build generated FROM the same source
in CI, not hand-maintained — Sol fix on drift), HN-tuned README with a Data Sources & Terms
section, CI split into blocking-fixture-tests vs scheduled-live-smoke.
accept: **fresh-venv install sim** (new venv, zero keys, empty cache dir) → `hotin hot` produces
a real board from the zero-key core; README renders; `pipx install .` works; blocking CI has no
network calls; a separate scheduled workflow exists for live-source health; `.gitignore` excludes
`.env`/cache/secrets (already true in the repo, re-verify).
bound: 2. exit → L5.

### L5 — RELEASE (HUMAN GATE)
goal: PyPI `hotin` package published, CI green on a clean runner, first tagged GitHub release.
accept: repo public (already true), CI green, `pipx install hotin` works end-to-end from PyPI.
Waits for Abe's go before any public announcement/HN post.
bound: n/a (human gate).

## repo_notes (goes in every executor plan)
- Python 3.9+, stdlib-first (urllib/sqlite3/argparse/json/concurrent.futures). Third-party deps
  only if they earn it; keep the required set tiny.
- Every adapter/parser is best-effort: total numeric coercion, isinstance guards on nested JSON,
  emit a `FetchResult(status="empty"|"error")` on any malformed shape — NEVER raise into the CLI.
- No secret in any committed file. Keys from `~/.config/hotin/.env` (600, atomic write, no
  symlink-follow) or env vars. `.env` already gitignored in `abe238/hotinai`.
- SQLite via stdlib `sqlite3`; FTS5 with a detected LIKE fallback; WAL; cache failure is a warning,
  never a crash.
- Match the finite/malformed-safe discipline already proven in the yt-tool-extraction sibling
  project: a JSON `1e309` must not produce an `Infinity` score; a non-list where a list is
  expected must degrade, not crash.
- All rendered strings pass through the ANSI/control-char sanitizer before hitting the terminal.
- No telemetry, ever.
