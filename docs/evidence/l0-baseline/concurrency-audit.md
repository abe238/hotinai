# L0 — concurrency audit

Re-verified at HEAD c4a6964 (2026-07-26).

`.github/workflows/refresh.yml`:
```yaml
concurrency:
  group: hotin-refresh
  cancel-in-progress: false
```

**Verdict: safe.** GitHub Actions concurrency groups with `cancel-in-progress: false`
QUEUE overlapping runs of this workflow rather than running them concurrently — a
second `refresh.yml` run triggered while one is in flight waits for the first to
finish rather than racing it. The "cross-dock JIT" read-modify-write race flagged
in the ideate run's trap-adjudication is already structurally prevented, **as long
as every new ledger write (tags.json, clicks.json, embeddings.json) stays inside
this same job** — a separate workflow file would NOT share this concurrency group
and would need its own guard. L4's weekly statistical-floor job reads (not writes)
the same files a refresh run writes, so it gets its own concurrency group scoped to
itself, documented in L4's task contract.
