# hotin — Reorg + Output Build Spec (locked 2026-07-21)

The single source of truth for the CLI reorg + output redesign. Visual reference:
`docs/design-board.html` (console / markdown / HTML, same data). Design tokens:
`DESIGN.md` (§ "Output color system"). Every change here is user-locked.

## 1. Command grammar

```
hotin <entity> [--source X] [--since Nd] [--min-stars N] [--format F] [--limit N] [--quiet] [--verbose]
```

**Bare `hotin` → `repos`** (default entity). No `hot` command, no `repos`/`releases`/`ingest`/`update` aliases.

### Entities (each self-ranked)
- `repos` — fused, corroboration-ranked AI repos (the flagship board)
- `people` — influencer AI-1000 (already shipped: `sources/insider_people.py`)
- `models` — HuggingFace trending + frontier-lab press releases (already built)
- `papers` — HuggingFace daily papers + HN papers (already built)
- `news` — smol.ai / AINews (already built)

### MANAGE verbs
- `brief` — one-shot digest across every entity
- `refresh` — **replaces both `ingest` and `update`**: refresh all sources + record a time-series snapshot + prune + report health. `--quiet` = headless/scheduler mode (the old `ingest` behavior, strict-persist exit code). Update the two callers: `~/.config/hotin/brief_telegram.py` and `.github/workflows/ingest.yml` (`-m hotin ingest` → `-m hotin refresh`).
- `setup` — config check; `--schedule daily|twice|off` installs the scheduled `hotin refresh`.
- `search <query>`, `show <owner/repo>`, `about`

### Removed / relocated
- `hn npm stars trending reddit youtube` are **no longer commands** → become `--source` values under `repos`.
- `--no-color` flag removed; color auto-disables when output is not a TTY (keep the existing TTY check). No `NO_COLOR` env handling required.

## 2. Global flags + validation (input must never crash)
- `--format {text,json,md,html}` — default `text`. `--json` is a documented shorthand for `--format json`. argparse `choices` → clean reject.
- `--limit N` — `type=int`, default **20** (was 50), `>=0` guard (existing message). Arbitrary-precision int, huge values are a harmless slice (verified).
- `--since Nd` — tolerant parser accepting `Nd|Nw|Nh` (days/weeks/hours). **Garbage (`--since abc`, `--since 5x`, empty) → clean error, never a traceback.** Applies where an entity has dates (repos/papers/news/models); no-op on `people`. Default: unset = no hard cutoff (freshness scoring already biases recent).
- `--min-stars N` — `type=int`, `>=0`, **repos only** (stars are a repo metric; no-op elsewhere).
- `--quiet` / `--verbose` retained. `--verbose` reveals the score (hidden by default).
- Sanitation is already robust (39 hostile inputs, 0 crashes) — preserve it: adapters never raise, FTS is parameterized, `canonicalize`/`sanitize` guard `show`/render. New flags must match this bar.

## 3. Output — one view-model, three renderers

Row view-model (every entity maps to it):
```
Row { rank, title, desc, url, receipts:[{source, value, rank_of?}], badges:[flag], score }
```

### Receipts = the numbers (who points at it), source-colored
`stars +N` (gained/week) · `npm N/wk` (weekly downloads) · `HN #N` (rank) · `reddit N` (score) · `youtube Nk` (views, when keyed). Source colors are fixed (DESIGN.md): npm #e06c5f, hn #ff922b, reddit #ff6b4a, stars #f2c65c. **Requires per-source signals retained through the merge** (available in `show`; thread into the list renderer).

### Badges = the verdicts (what it means), outline chips
- `fresh` — new or recently active
- `smart-money` — ≥2 influencer AI-1000 accounts starred it AND ≥2 sources
- `paper-backed` — linked from a currently-trending paper
- `trending` — on GitHub's / the public repo-trends API's **own** top-list (external corroboration; top ~25, selective). **Viral folded in as one intensity step**: normal = dim violet outline; viral (multiple external lists + accelerating) = bright violet + soft glow.
- `rising`/`viral` are **no longer separate badges** — rising is shown by the receipt number; viral is the glow intensity of `trending`.

### Per-surface rendering (surfaces render what they CAN)
| Surface | Rows | Badges | Viral intensity |
|---|---|---|---|
| **console** (`text`) | rank · `repo - desc` (desc dim, inline) · receipts (source-colored) · badges | **colored text** (terminals can't draw borders/glow) | bright + bold violet |
| **markdown** (`md`) | table: #, Repo - desc, Signals, badges | `` `code` `` / plain | **bold** |
| **html** (`html`) | ranked cards | **outline chips** (source-dot) | brighter outline + glow |

Row is **rank-led** (score behind `--verbose`), description **inline** after the repo (`repo - desc`). Badges stack (a repo can be `trending smart-money fresh`).

### Ranking honesty
Freshness scoring must keep established mega-repos (llama.cpp, pytorch) out of the top unless a genuine burst (release star-spike or paper link). The `trending` badge (external, velocity-based) reinforces this — a flat-velocity giant earns neither trending nor fresh.

## 4. New source: `sources/trends_ai.py`
The public repo-trends AI collections (the `/trending/ai` engine), stdlib-only, no key.
- `GET https://api.ossinsight.io/v1/collections/` → filter to AI-topic collections.
- `GET /v1/collections/{id}/ranking_by_stars/?period=past_28_days` → rows with `current_period_growth` (star-growth delta), `total`, `current_period_rank`.
- Emit repo records; feed `repos` corroboration + the `trending` badge (this repo is on the public repo-trends AI trending) + the `stars +N` receipt (growth delta). Best-effort contract (`fetch(query, limit, config) -> {records, status, detail}`), never raises. Ships with tests.

## 5. Deferred (documented, NOT this build)
`--category` filter (adopt only if volume justifies), `github.com/trending` scrape, `/trending/developers` → `people --source github`, multi-feed `news` RSS, `youtube Nk` receipt polish.

## 6. Acceptance
- 210+ existing tests stay green; new tests for `refresh`, `--format`, `--since` parsing, `trends_ai`.
- Live-drive every touched command via the repo `verify` skill (real CLI): `hotin`, `hotin --help` (grouped), `hotin repos --source hn`, `hotin repos --since 30d --min-stars 500`, `hotin --format md|html|json`, `hotin refresh --quiet`, `hotin models/papers/people/news`.
- `--format html` output matches `docs/design-board.html`'s language; `--format md` matches its markdown section.
- Input-sanitation battery still 0 crashes, now including the new flags.
