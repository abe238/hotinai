# hotin — what's hot in AI, from your terminal

**hotin** is an open-source CLI that surfaces what's hot, fresh, and viral in AI right now —
across GitHub trending repos, Hacker News, npm adoption, Reddit, YouTube, and "smart money"
(which credible AI-influencer accounts are starring things). It ranks by cross-source
**corroboration** (agreement across independent sources beats any single signal) and
**freshness** (recency-weighted, so stale results decay).

```
$ hotin
```

- **Zero setup.** Python 3.9+ is the only hard requirement. SQLite (bundled) is the only
  storage — no database server, no Postgres, no pgvector.
- **Works on a fresh machine, instantly.** Momentum is sourced live (GitHub/the public repo-trends API/npm),
  not from accumulated local history — though running `hotin update` on a schedule sharpens
  it over time.
- **Every source degrades gracefully.** A missing API key or a down source never breaks a run.

## Status

🚧 Under active construction. Follow along at [hotin.ai](https://hotin.ai) and this repo.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

You're free to use, fork, and build commercial products on top of hotin. The Apache
license requires any redistributed copy or derivative to retain the attribution notice
in [NOTICE](NOTICE) — if hotin (the code, the ranking approach, or the idea) inspired
your project, please keep that credit and a link back to
[github.com/abe238/hotinai](https://github.com/abe238/hotinai).

---

*Made by [@abe238](https://github.com/abe238) · [hotin.ai](https://hotin.ai)*
