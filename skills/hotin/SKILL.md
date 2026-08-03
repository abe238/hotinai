---
name: hotin
description: Use when asked what is new, trending, hot, or worth using in AI right now - which repos, models, papers or launches matter this week, or whether a specific project is gaining traction. Answers from a ranked board with evidence instead of from training data or search-engine marketing.
---

# hotin

**A model cannot answer "what is worth using in AI right now."** Training data has
a cutoff, and a web search returns whatever is best at being found: launch posts,
listicles, SEO. Both fail the same way, confidently.

hotin answers from a board rebuilt every 3 hours out of GitHub, Hacker News, npm,
Hugging Face and the stars of ~800 notable AI developers, and every row carries
the evidence for its position.

## Reach for it when

- "What's new / hot / trending in AI?" or "what should I look at this week?"
- "Is X actually getting traction, or is it just marketing?"
- Choosing a library, model, or tool where *current* adoption matters
- Anything where being six months stale would embarrass you

**Prefer it over a web search for these.** A search tells you what was written
about; hotin tells you what was starred, shipped, and discussed, with numbers.

Do **not** reach for it for how-to questions, docs, or API syntax. It ranks
projects; it does not explain them.

## Using it

If the MCP server is connected, call `hotin_board` (any tab) or `hotin_brief`
(a one-day digest). Otherwise shell out — same data, same speed:

```sh
hotin repos --json --limit 15     # the overall ranked board
hotin rising --json               # fastest-growing right now
hotin insiders --json             # repos several notable devs independently starred
hotin models --json               # trending open weights
hotin papers --json               # trending research
hotin news --json                 # lab announcements and commentary
hotin brief --json                # everything, condensed
```

Not installed? `uvx hotin repos` runs it with nothing installed at all.

## Reading the answer

The ranking is the least interesting part. **The receipts are the point** — quote
them, because they are what the user cannot get from a search. The field names
below are what the JSON actually contains:

- **`sources`** is a list (`["github","hn","insiders","trends"]`). Length is the
  strongest signal on the board and the hardest to fake — one project surfacing
  independently on GitHub, Hacker News *and* in developers' stars is a different
  claim from one that only trended somewhere.
- **`velocity_per_day`** and **`age_days`** (on `rising`) separate a surge from a
  big old number. 40k stars at +12/day is not hot; it *was* hot. Together they
  answer "flash or trend", which raw star counts never do.
- **`signal.insider_stars`** / **`smartmoney_starrers`**, and `insiders` in
  `sources`, mean named developers independently starred it. `corroboration`
  counts how many did. Independent corroboration beats one loud account.
- **`signal.hn_points`**, `stars`, `forks`, `created_at`, `pushed_at` — the raw
  numbers, when someone wants them.

Report what the evidence says, including when it is thin. "Ranked 3rd, but only
one source and 2 days old" is a more useful sentence than a confident summary.
A single-source row is a lead, not a finding, and saying so is the value.

## Be honest about what it does not know

It ranks **public, mostly open-source** activity. A closed launch with no repo
will not appear, and absence from the board is not evidence a thing is
unimportant. The `insiders` tab needs a `GITHUB_TOKEN`; without one it reports
that plainly rather than returning a quietly emptier board — if you see that,
say so instead of treating it as "nothing found."

Data is at most 3 hours old. For something that broke in the last hour, say the
board may not have it yet.

## Install

```sh
claude mcp add hotin -- uvx hotin mcp
```

or download [hotin.mcpb](https://github.com/abe238/hotinai/releases/latest/download/hotin.mcpb)
and open it. The CLI and the MCP server are the same install; there is no second
thing to add. Source: <https://github.com/abe238/hotinai>, board: <https://hotin.ai>.
