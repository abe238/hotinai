# hotinai

What's hot in AI right now — repos, models, papers and news, ranked daily by
cross-source consensus. Every repo is security-assessed before it appears.

This npm package is a launcher for the Python `hotin` CLI:

```bash
npx hotinai            # today's board in your terminal
npx hotinai mcp        # run the MCP server (Claude Code / Cursor / Codex)
```

It runs an existing `hotin` install if present, otherwise `uvx hotin`, otherwise
`pipx run hotin`. Python natives can skip node entirely: `pip install hotin`.

Site: https://hotin.ai — Source: https://github.com/abe238/hotinai

## Source and provenance

This launcher's source lives in [`npm/`](https://github.com/abe238/hotinai/tree/main/npm)
in the main repository, and is published by GitHub Actions on release with
[npm provenance](https://docs.npmjs.com/generating-provenance-statements), so the
published tarball is cryptographically linked to the commit it was built from.

Licensed Apache-2.0, the same as the rest of the project.
