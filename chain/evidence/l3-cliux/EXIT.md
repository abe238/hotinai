# L3 — CLI UX · EXIT (2026-07-20)
## Status: COMPLETE
## Headline
All 12 subcommands wired for real: hot, hn, npm, stars, trending, reddit, youtube, search, show,
setup, update, about. Beautiful ANSI-safe rendering (a shared _safe() helper wraps render.sanitize()
across every print path), badge coloring, the never-spammy attribution footer (first-run marker
file, always suppressed by --quiet/--json/non-tty except on `about` where it's intentional
primary content). 160 tests green.
## A real, pre-existing bug found and fixed as part of this loop
hot's human-readable output printed repo["name"] completely unsanitized (HN post titles are free
text and could carry ANSI/bidi control sequences). Fixed by generalizing sanitization into a
shared _safe() helper used consistently across ALL render paths, not just hot's — confirmed via
a hostile-content regression test AND direct source inspection.
## Bound accounting
1 cross-model (Sol) review, no P1s. 2 real P2/P3 findings, both fixed and independently
re-verified (with a genuine follow-on bug caught in my own first fix, corrected before landing):
- show --json printed a human sentence instead of JSON for a missing repo, breaking pipelines.
- _dump_json's exception guard only caught ValueError, not TypeError (a malformed adapter
  returning e.g. a tuple-keyed dict would crash JSON output) - fixed, AND the first attempted fix
  had its own bug (the fallback path didn't actually coerce bad dict keys) - caught by re-running
  the exact reproduction, not assumed fixed from the diff alone.
`about --quiet`/non-tty showing attribution was flagged by Sol but is BY DESIGN (about's whole
purpose is showing project info) — no fix, working as originally specified.
## exit -> L4 (already parallel-built) + final commit
