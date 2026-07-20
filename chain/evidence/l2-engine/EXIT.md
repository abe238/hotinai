# L2 — ENGINE · EXIT (2026-07-20)
## Status: COMPLETE
## Headline
The ranking engine: concurrent fetch across all 8 adapters, merge-by-canonical-repo,
momentum+credibility+signal scoring with corroboration and freshness multipliers, the 6-core
category classifier, and the real `hotin hot` command. 136 tests green. Proven end-to-end live
with a genuinely fresh cache and zero API keys: 25.2s total, exit 0, real corroborated output
(justvugg/colibri surfaced via both hn AND trends, correct per-source provenance).
## Two real defects found ONLY by live testing (not by review alone) — verified by hand,
not trusted from the executor's self-report
1. `fetch_all()`'s sequential per-future `.result(timeout=X)` loop let total wall-clock approach
   num_adapters × timeout (confirmed: 90+s hang on the first live run). Fixed with
   `concurrent.futures.wait(futures, timeout=timeout)` — one deadline for the whole batch, hand-
   verified: fetch_all() now genuinely returns at exactly the timeout value with correct
   per-source statuses (npm correctly reported as timed-out when it doesn't finish in time).
2. Even after fix #1, the FULL CLI PROCESS still hung past 50s — root-caused precisely (isolated
   fetch_all() from the full CLI, proved the function itself returns promptly but the process
   doesn't exit): Python's ThreadPoolExecutor worker threads are non-daemon, so an abandoned
   slow adapter thread (npm, still running its throttled sequence in the background) blocks
   the interpreter's default shutdown-wait-for-non-daemon-threads behavior. Fixed with an
   explicit `os._exit()` after flushing output, scoped narrowly to the hot command's success
   path only. Re-verified: full end-to-end timed run now completes in 25.2s, not 90+.
## Bound accounting
1 cross-model (Sol) review, decisive on a real architecture question: fix cache.py's
url-mangling-avoidance schema NOW (composite UNIQUE(url,source), correct FTS rowid join, real
urls retained) rather than defer the landmine to L3's search/show commands. Also found and fixed:
missing engine-level canonicalization in merge, npm momentum using the wrong field (absolute
downloads vs documented growth), an uncapped smart-money term that could dominate corroboration
(hand-verified post-fix: 3-source corroboration beats extreme uncapped smart-money, 25.92 vs
12.00), lost per-source provenance during merge (now `signal_by_source`), missing health status
in --json output, a --limit 0 bug, and NaN/Infinity JSON safety. All independently hand-verified
after the fix, not just re-run from terra's own tests.
## Verified live
`hotin hot --json --limit 5` on a genuinely fresh, empty cache with zero API keys: 25.236s total,
exit 0, real cross-source corroboration in the output.
## exit -> L3 (CLI UX): full subcommand set, beautiful terminal rendering, attribution
