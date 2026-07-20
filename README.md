# hotin — what's hot in AI, from your terminal

An open-source CLI for finding what's hot, fresh, and credible in AI.

hotin pulls together independent signals and ranks projects by cross-source corroboration and freshness, so a tool gaining attention in more than one place has more weight than a one-source spike.

## What it does

The zero-key core combines GitHub Trending, the public repo-trends API momentum, Hacker News, and npm velocity with no configuration. Add an optional key to unlock Reddit and YouTube (ScrapeCreators, or the official YouTube Data API v3), including curated repo-roundup channels. A the influencer-stars source-based “smart money” credibility signal is included on a best-effort basis, and smol.ai/AINews adds an editorial corroboration flag. Sources can be temporarily unavailable without taking down the CLI.

Beyond repos, hotin surfaces trending **AI models** (`hotin models`) and **papers** (`hotin papers`) as their own views, and a short daily **`hotin brief`** of what's happening across all of them. Run `hotin ingest` on a schedule (a GitHub Actions cron is included) and hotin records a time series, so `hotin hot` can flag what's genuinely **rising** and **viral** (velocity, not just a snapshot) — not just what's big right now.

## Install

Once hotin is published to PyPI, the standard install will be:

```sh
pip install hotin
```

From a checkout during pre-release development:

```sh
pip install -e .
```

Or install the current repository with pipx:

```sh
pipx install git+https://github.com/abe238/hotinai
```

A prebuilt single-file `hotin.pyz` will be attached to GitHub Releases as a zero-install option for a fresh machine. Run it with:

```sh
python hotin.pyz hot
```

## Quick start

```sh
hotin hot
```

Available commands:

| Command | Description |
| --- | --- |
| `hotin hot` | show the hottest AI tools |
| `hotin repos` | the hottest repos (same ranking as `hot`) |
| `hotin news` | recent AI news headlines (smol.ai / AINews) |
| `hotin hn` | show Hacker News signals |
| `hotin npm` | show npm signals |
| `hotin stars` | show GitHub star growth |
| `hotin trending` | show trending repositories |
| `hotin reddit` | show Reddit signals |
| `hotin youtube` | show YouTube signals |
| `hotin models` | show trending AI models (HuggingFace) |
| `hotin papers` | show trending AI papers (HuggingFace) |
| `hotin brief` | a short daily digest of what's happening in AI |
| `hotin search <query>` | search cached tools |
| `hotin show <owner/repo>` | show one tool |
| `hotin setup` | check local configuration |
| `hotin update` | refresh all sources |
| `hotin ingest` | refresh + record the time series (for a scheduler) |
| `hotin about` | show project information |

Each repo result presents a score, the owner/repo (clickable), category, and applicable badges: `fresh` (recently created or active), `rising` / `viral` (climbing fast on the recorded time series, `viral` being the rare accelerating-and-corroborated extreme), `smart-money` (credible AI accounts on it across several sources), and `paper-backed` (linked from a trending paper). Corroboration across sources is folded into the score itself, not shown as a badge.

Example (real output, top of a live run):

```text
$ hotin hot --limit 8
 30.59  xai-org/grok-build  agents  fresh
        Grok Build is open source
 22.17  justvugg/colibri  uncategorized
        Show HN: Getting GLM 5.2 running on my slow computer
 17.05  dietrichgebert/ponytail  app-building  fresh
 17.00  odysseus-dev/odysseus  uncategorized  fresh
 16.93  nexu-io/open-design  agents  fresh
 15.46  yuan1z0825/nature-skills  uncategorized  fresh
 15.24  bigpizzav3/codexplusplus  uncategorized  fresh
 14.77  antirez/ds4  inference  fresh
```

The first line of each result is score, owner/repo (clickable in a real terminal), category, and badges; a dimmed second line shows the human title when it adds context the slug doesn't. `fresh` reflects recent repository activity. In a live terminal the score and badges are colored. Your output will differ — it reflects what is actually hot when you run it.

## Data Sources & Terms

hotin's code is licensed under Apache-2.0. That license does not relicense the underlying data returned by GitHub, Hacker News, npm, Reddit, YouTube, or the influencer-stars source: each source's own terms of use apply.

The Reddit and YouTube integrations are unofficial third-party integrations via ScrapeCreators; they are not officially sanctioned by Reddit or YouTube. The the influencer-stars source-based smart-money signal is a best-effort scrape of the influencer-stars source's public page and may change or break without notice.

## Contributing

Issues and contributions are welcome at the [issue tracker](https://github.com/abe238/hotinai/issues).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

hotin was created by [Abe Diaz](https://github.com/abe238). If hotin, its ranking approach, or its ideas helped your project, a credit and link back to [github.com/abe238/hotinai](https://github.com/abe238/hotinai) are appreciated.

*Made by [@abe238](https://github.com/abe238) · [hotin.ai](https://hotin.ai)*
