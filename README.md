# hotin — what's hot in AI, from your terminal

An open-source CLI for finding what's hot, fresh, and credible in AI.

hotin pulls together independent signals and ranks projects by cross-source consensus and freshness, so a tool gaining attention in more than one place has more weight than a one-source spike.

## What it does

The zero-key core combines GitHub Trending, curated growth momentum, Hacker News, and npm velocity with no configuration. Add an optional key to unlock Reddit and YouTube (ScrapeCreators, or the official YouTube Data API v3), including curated repo-roundup channels. A “smart money” signal (repos the AI Insiders are backing) is included on a best-effort basis, and an AI-newsletter feed adds an editorial signal. Sources can be temporarily unavailable without taking down the CLI.

Beyond repos, hotin surfaces trending **AI models** (`hotin models`) and **papers** (`hotin papers`) as their own views, and a short daily **`hotin brief`** of what's happening across all of them. Run `hotin refresh` on a schedule and hotin records a time series, so the board can flag what's genuinely **rising** and **viral** (velocity, not just a snapshot) — not just what's big right now.

## Install

```sh
pip install hotin
```

hotin has zero dependencies, so a plain `pip install` is safe (nothing to conflict with). Prefer an isolated install, or don't want to install at all?

```sh
uvx hotin              # run without installing (needs uv)
uv tool install hotin  # persistent command via uv
pipx install hotin     # persistent command via pipx
```

No package manager, just Python? Grab the single-file `hotin.pyz` from the [latest release](https://github.com/abe238/hotinai/releases/latest) and run it:

```sh
python hotin.pyz
```

Developing on a checkout: `pip install -e .`.

## Quick start

```sh
hotin
```

Available commands:

| Command | Description |
| --- | --- |
| `hotin` | the flagship board (defaults to `repos`) |
| `hotin repos` | trending AI repos, fused across sources |
| `hotin insiders` | repos the AI Insiders are backing (the smart-money signal) |
| `hotin models` | AI models — lab press releases + trending weights |
| `hotin papers` | trending AI papers |
| `hotin news` | recent AI news headlines |
| `hotin brief` | a one-shot digest across every entity |
| `hotin refresh` | refresh all sources + record a snapshot (`--quiet` = headless) |
| `hotin export` | write the board to `docs/index.html` + `latest.json` |
| `hotin setup` | check config, or schedule automatic refreshes |
| `hotin search <query>` | search cached repos |
| `hotin show <owner/repo>` | show one repo |
| `hotin about` | show project information |

**Flags:** `--format text\|json\|md\|html` · `--limit N` (default 20) · `--source <name>` (repos: one upstream feed instead of the fused board) · `--since 30d` / `--min-stars N` (repos filters) · `--verbose`.

Each repo result presents a score, the owner/repo (clickable), category, and applicable badges: `fresh` (recently created or active), `rising` / `viral` (climbing fast on the recorded time series, `viral` being the rare accelerating-and-consensus extreme), `smart-money` (the AI Insiders are backing it), and `paper-backed` (linked from a trending paper). Consensus across sources is folded into the score itself, not shown as a badge.

Example (real output, top of a live run):

```text
$ hotin --limit 8
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

## Keeping it fresh

hotin's `rising` / `viral` badges and the `hotin brief` come from a recorded time series, so they get better the more often `hotin refresh` runs. `hotin setup` can install a scheduled job for you:

```sh
hotin setup                     # interactive: once a day (8am) or twice (8am & 8pm)
hotin setup --schedule twice    # non-interactive: 8am & 8pm
hotin setup --schedule daily    # 8am only
hotin setup --schedule off      # remove it
```

On macOS/Linux this manages a marked block in your `crontab`; on Windows it creates `hotin-refresh` scheduled tasks. Either way it runs `python -m hotin refresh --quiet`, leaving the rest of your schedule untouched.

## Data Sources & Terms

hotin's code is licensed under Apache-2.0. That license does not relicense the underlying data returned by GitHub, Hacker News, npm, Reddit, or YouTube: each source's own terms of use apply.

The Reddit and YouTube integrations are unofficial third-party integrations via ScrapeCreators; they are not officially sanctioned by Reddit or YouTube. The smart-money signal is a best-effort read of a public AI-influencer graph and may change or break without notice.

## Contributing

Issues and contributions are welcome at the [issue tracker](https://github.com/abe238/hotinai/issues).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

hotin was created by [Abe Diaz](https://github.com/abe238). If hotin, its ranking approach, or its ideas helped your project, a credit and link back to [github.com/abe238/hotinai](https://github.com/abe238/hotinai) are appreciated.

*Made by [@abe238](https://github.com/abe238) · [hotin.ai](https://hotin.ai)*
