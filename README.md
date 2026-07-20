# hotin — what's hot in AI, from your terminal

An open-source CLI for finding what's hot, fresh, and credible in AI.

hotin pulls together independent signals and ranks projects by cross-source corroboration and freshness, so a tool gaining attention in more than one place has more weight than a one-source spike.

## What it does

The zero-key core combines GitHub Trending, the public repo-trends API momentum, Hacker News, and npm velocity with no configuration. Add an optional ScrapeCreators API key to unlock Reddit and YouTube signals. A the influencer-stars source-based “smart money” credibility signal is also included on a best-effort basis. Sources can be temporarily unavailable without taking down the CLI.

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
| `hotin hn` | show Hacker News signals |
| `hotin npm` | show npm signals |
| `hotin stars` | show GitHub star growth |
| `hotin trending` | show trending repositories |
| `hotin reddit` | show Reddit signals |
| `hotin youtube` | show YouTube signals |
| `hotin search <query>` | search cached tools |
| `hotin show <owner/repo>` | show one tool |
| `hotin setup` | check local configuration |
| `hotin update` | update hotin |
| `hotin about` | show project information |

Each result presents a score, repository name, category, and applicable badges such as `fresh`, `smart-money`, and `corroborated`.

Example (real output, top of a live run):

```text
$ hotin hot --limit 8
30.55  Grok Build is open source                          agents         new,fresh,hn
22.89  Show HN: Getting GLM 5.2 running on my slow computer  uncategorized  hn
17.05  DietrichGebert/ponytail                             app-building   new,fresh
17.00  odysseus-dev/odysseus                               uncategorized  new,fresh
16.93  nexu-io/open-design                                 agents         new,fresh
15.46  Yuan1z0825/nature-skills                            uncategorized  new,fresh
15.24  BigPizzaV3/CodexPlusPlus                            uncategorized  new,fresh
14.77  antirez/ds4                                         inference      new,fresh
```

The columns are score, name, category, and badges. `hn` here means the item was corroborated by a Hacker News signal; `new`/`fresh` reflect recent creation and recent repository activity. Your output will differ — it reflects what is actually hot when you run it.

## Data Sources & Terms

hotin's code is licensed under Apache-2.0. That license does not relicense the underlying data returned by GitHub, Hacker News, npm, Reddit, YouTube, or the influencer-stars source: each source's own terms of use apply.

The Reddit and YouTube integrations are unofficial third-party integrations via ScrapeCreators; they are not officially sanctioned by Reddit or YouTube. The the influencer-stars source-based smart-money signal is a best-effort scrape of the influencer-stars source's public page and may change or break without notice.

## Contributing

Issues and contributions are welcome at the [issue tracker](https://github.com/abe238/hotinai/issues).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

hotin was created by [Abe Diaz](https://github.com/abe238). If hotin, its ranking approach, or its ideas helped your project, a credit and link back to [github.com/abe238/hotinai](https://github.com/abe238/hotinai) are appreciated.

*Made by [@abe238](https://github.com/abe238) · [hotin.ai](https://hotin.ai)*
