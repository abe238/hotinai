#!/usr/bin/env node
// hotinai -- npm shim for the Python `hotin` CLI (https://hotin.ai)
// Resolution order: existing `hotin` on PATH, then uvx, then pipx.
const { spawnSync } = require("child_process");
const args = process.argv.slice(2);

function has(cmd) {
  const probe = process.platform === "win32" ? "where" : "which";
  return spawnSync(probe, [cmd], { stdio: "ignore" }).status === 0;
}
function run(cmd, pre) {
  const r = spawnSync(cmd, [...pre, ...args], { stdio: "inherit" });
  process.exit(r.status === null ? 1 : r.status);
}

if (has("hotin")) run("hotin", []);
if (has("uvx")) run("uvx", ["hotin"]);
if (has("pipx")) run("pipx", ["run", "hotin"]);

console.error(
  "hotin is a Python CLI; this npm package is a launcher and needs one of:\n" +
  "  - uv    : curl -LsSf https://astral.sh/uv/install.sh | sh   (then re-run)\n" +
  "  - pipx  : brew install pipx / pip install pipx\n" +
  "  - pip   : pip install hotin\n" +
  "Docs: https://hotin.ai"
);
process.exit(1);
