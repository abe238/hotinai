---
name: verify
description: How to build and drive the real hotin CLI for verification (not tests).
---

# Verifying hotin

hotin is a stdlib-only Python CLI (`pyproject.toml` entry point `hotin = "hotin.cli:main"`).
Zero-key core (github, trends, hn, npm) hits real public APIs with no config.

## Build a handle

```bash
python3 -m venv /tmp/hotin_verify_venv
source /tmp/hotin_verify_venv/bin/activate
pip install --quiet -e .
export XDG_DATA_HOME=/tmp/hotin_verify_xdg   # isolates the sqlite cache from ~/.local/share
```

`hotin` is now a real binary on PATH. Config lives at `~/.config/hotin/.env` (XDG_CONFIG_HOME,
not XDG_DATA_HOME) — `setup --check` reads it directly, unaffected by the cache override above.

## Drive it

- `hotin about` / `hotin setup --check` — no network, sanity check the install.
- `hotin hn --limit 3` — one real live call, fast, good smoke test of the free-text
  GitHub-reference extraction (hn/reddit/youtube share this mechanism).
- `hotin hot --limit N --json` — the real end-to-end surface: fetch_all() across all 8
  adapters concurrently, cache, merge, rank. Takes ~25s (the fetch_all timeout ceiling) if
  any source is slow/failing — see gotcha below. Re-running within 300s (default TTL) should
  make previously-successful sources report `"served from cache"` and skip the network.
- `hotin search <query> --json`, `hotin show <owner/repo> --json` — cache-only, instant,
  exercise the merge/score path without any network.
- Probe error paths: `search` with no query (exit 2), negative `--limit` (exit 2), `show` on
  an uncached repo (clean JSON `{"error": "not_cached", ...}`, exit 0).

## Known gotcha: npm always times out

`hotin.sources.npm.fetch()` does one search request per `DEFAULT_QUERIES` term, then one
THROTTLE-gated (1.5s+jitter) download-stats request **per candidate package, sequentially**.
With 5 query terms × up to 40 results each, that's typically 30-100+ unique candidates —
90-300+ seconds of pure throttle wait, blowing straight through `engine.fetch_all`'s 25s
per-cycle budget. Confirmed live 2026-07-19: npm reports `"error", "timed out"` on every
`hot` run, first run AND subsequent warm-cache runs (since it never successfully populates
its own cache entry, it's never "fresh" and always retries the full 25s). This is a known,
reliably-reproducible issue, not flaky — don't waste another live run "confirming" it again.

## Rebuild the single-file distribution after touching src/hotin/

```bash
sh scripts/build_zipapp.sh
python3 dist/hotin.pyz --help
python3 -c "import zipfile; print(zipfile.ZipFile('dist/hotin.pyz').namelist())"  # confirm new files are staged
```
`scripts/build_zipapp.sh` does a fresh `cp -R src/hotin` each run, so new modules are picked
up automatically — no manual list to maintain.

## Be kind to servers

Every adapter fetch hits a real public API. Don't loop `hot`/`hn`/etc. repeatedly to "be
sure" — one clean live run per surface is enough evidence. `search`/`show` are cache-only and
safe to run freely.
