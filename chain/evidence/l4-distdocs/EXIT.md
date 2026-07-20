# L4 — DIST & DOCS · EXIT (2026-07-20)
## Status: COMPLETE
## Headline
pyproject.toml release metadata (classifiers, keywords, URLs, Apache-2.0, no personal email),
HN-tuned README with a Data Sources & Terms section (no fabricated example output — a TODO
marker was left honestly since this loop ran in parallel with L3 and had no access to real
rendering), split CI (ci.yml blocking/fast/network-free; live-smoke.yml scheduled/non-blocking),
a generated (not hand-maintained) single-file dist/hotin.pyz via stdlib zipapp.
## Built in parallel with L3 (genuinely disjoint files, no worktree isolation needed)
Verified no file-level conflict; both loops' diffs landed cleanly in the same working tree.
## Bound accounting
1 cross-model (Sol) review, no P1s. 2 real findings in scripts/build_zipapp.sh, both fixed and
re-verified against Sol's exact reproduction:
- zipapp's -m flag drops CLI exit codes (main() called without sys.exit()) - confirmed live:
  `hotin.pyz hn --limit -1` exited 0 instead of 2. Fixed with a real __main__.py doing
  `raise SystemExit(main())`. Re-verified: exit code now correctly 2.
- the archive included __pycache__/egg-info cruft from the local workspace - fixed by staging a
  clean copy of just src/hotin/ before building. Re-verified: 0 cruft files in the archive.
## exit -> L5 (HUMAN GATE), after /simplify -> /verify -> /code-review per Abe's request
