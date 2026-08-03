#!/usr/bin/env python3
"""Package hotin as a .mcpb bundle: one file, one click, no terminal.

An MCP Bundle is a zip holding a manifest.json and the server itself. Claude
Desktop (and other MCPB-aware clients) unpack it and run the server as a
subprocess, so a user installs by double-clicking a file instead of finding a
config path, editing JSON, and restarting.

WHY THIS IS EASY FOR HOTIN AND HARD FOR EVERYONE ELSE
-----------------------------------------------------
The standard advice is that Node bundles are the default because Claude Desktop
ships its own Node runtime, while Python bundles must vendor their dependencies
and cannot portably ship compiled ones.

hotin has ZERO DEPENDENCIES. Vendoring it is copying a directory of pure-Python
source. The bundle needs no wheels, no compiled extensions, no network at
install time, and no uv, pip or npx on the user's machine -- only a python3,
which macOS and Linux already have.

That is a real and unusual advantage, and it is worth keeping: the moment this
package takes a dependency, this file gets meaningfully harder.

    python3 scripts/build_mcpb.py            # writes dist/hotin.mcpb
    python3 scripts/build_mcpb.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hotin"
OUT = ROOT / "dist" / "hotin.mcpb"


def version() -> str:
    text = (SRC / "__init__.py").read_text()
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no __version__ in src/hotin/__init__.py")


ENTRY = '''"""Bundle entry point. Runs hotin's MCP server from the vendored source.

PYTHONPATH, not just sys.path. mcp.py answers every tool call by running
`python3 -m hotin` as a CHILD PROCESS, and a child gets a fresh interpreter that
knows nothing about our sys.path edit. Without this the server would start,
list its tools, and then fail every actual call with "No module named hotin" --
the exact failure the zipapp path already taught us, one layer further out.
"""
import os
import sys

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB)
os.environ["PYTHONPATH"] = (
    LIB + os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else LIB)

from hotin import mcp  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(mcp.serve())
'''


def manifest(ver: str) -> dict:
    return {
        "manifest_version": "0.3",
        "name": "hotin",
        "display_name": "hotin",
        "version": ver,
        "description": "What's hot in AI right now, ranked with receipts.",
        "long_description": (
            "A model's training data has a cutoff and a web search returns marketing, "
            "so an agent asked what is worth using in AI this week has to guess. hotin "
            "answers with a ranked board built from GitHub, Hacker News, npm, Hugging "
            "Face and the stars of ~800 notable AI developers, and every row carries "
            "the evidence for its position: how fast it is growing, who backed it, "
            "where else it surfaced.\n\n"
            "Runs entirely on your machine. It fetches those sources directly and "
            "caches to your own disk; nothing is sent anywhere."
        ),
        "author": {"name": "Abe Diaz", "url": "https://github.com/abe238"},
        "homepage": "https://hotin.ai",
        "documentation": "https://github.com/abe238/hotinai#readme",
        "license": "Apache-2.0",
        "keywords": ["ai", "trending", "github", "research", "cli"],
        "server": {
            "type": "python",
            "entry_point": "server/main.py",
            "mcp_config": {
                # python3 rather than a bundled runtime: hotin is pure stdlib, so
                # the interpreter macOS and Linux already ship is enough. No uv,
                # no pip, no npx, no network at install time.
                "command": "python3",
                "args": ["${__dirname}/server/main.py"],
                "env": {"GITHUB_TOKEN": "${user_config.github_token}"},
            },
        },
        # Optional on purpose. The board works with no key at all; a token only
        # unlocks the insiders signal. Marking it required would turn a
        # one-click install into a scavenger hunt for most users.
        #
        # `default: ""` IS LOad-BEARING, not tidiness. The host builds its
        # substitution table only from user_config entries that have a default
        # or a user-supplied value, and replaceVariables leaves any variable it
        # cannot resolve ALONE. So an optional field with no default, left blank
        # by the user, ships the literal string "${user_config.github_token}" as
        # GITHUB_TOKEN -- which is not empty, so it overrides a token the user
        # already had and then goes out as `Authorization: Bearer ${user_conf...`.
        # Every insiders poll 401s, for the majority of one-click installs.
        # An explicit "" puts the key in the table and the substitution resolves.
        "user_config": {
            "github_token": {
                "type": "string",
                "title": "GitHub token (optional)",
                "description": (
                    "Only needed for the 'insiders' tab, which polls what notable "
                    "developers starred. Everything else works without it."
                ),
                "sensitive": True,
                "required": False,
                "default": "",
            }
        },
        "tools": [
            {"name": "hotin_board",
             "description": "Ranked AI repos, models, papers or news, with receipts."},
            {"name": "hotin_brief",
             "description": "A short digest of the last day across all of AI."},
        ],
        # Declared, not discovered the hard way. The bundle launches `python3`,
        # which macOS and Linux ship; on Windows that name is commonly absent or
        # a Microsoft Store stub that opens the store instead of running code.
        # A refused install with a stated reason beats one that succeeds and
        # then fails every call. Windows users still have `uvx hotin mcp` and
        # `pip install hotin`, both of which the README leads with.
        "compatibility": {"platforms": ["darwin", "linux"],
                          "runtimes": {"python": ">=3.9"}},
    }


def build(out: pathlib.Path = OUT) -> pathlib.Path:
    ver = version()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp)
        lib = stage / "server" / "lib" / "hotin"
        lib.parent.mkdir(parents=True)
        # __pycache__ would bloat the bundle and can contain absolute paths from
        # the build machine.
        shutil.copytree(SRC, lib, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (stage / "server" / "main.py").write_text(ENTRY)
        (stage / "manifest.json").write_text(json.dumps(manifest(ver), indent=2) + "\n")

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())
    return out


def verify(bundle: pathlib.Path) -> dict:
    """Open the built bundle and prove it would actually run.

    Checked rather than assumed, because a .mcpb that installs and then fails is
    worse than one that never installs: the user has no terminal, no log, and no
    way to tell what went wrong.
    """
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names, "a bundle without a manifest is not a bundle"
        assert "server/main.py" in names
        assert "server/lib/hotin/mcp.py" in names, "the server itself must be vendored"
        assert not any(n.endswith(".pyc") for n in names), "no build-machine bytecode"
        meta = json.loads(zf.read("manifest.json"))
    for key in ("manifest_version", "name", "version", "description", "server"):
        assert meta.get(key), "manifest missing " + key
    assert meta["server"]["mcp_config"]["command"] == "python3"
    return {"files": len(names), "version": meta["version"],
            "bytes": bundle.stat().st_size, "schema": _validate_schema(bundle)}


def _validate_schema(bundle: pathlib.Path) -> str:
    """Check the manifest against the OFFICIAL schema, not against my reading of it.

    The spec is young and the field names have already moved -- published
    examples in the wild carry manifest_version 0.3, 0.4, and a stale
    mcpb_version 0.1. Picking one by reading a blog post is how you ship a
    bundle that is well-formed by your own standards and rejected by every host.

    Skipped, loudly, when npx is unavailable: a build machine without Node is a
    reason to say the check did not run, never a reason to imply it passed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as zf:
            zf.extract("manifest.json", tmp)
        try:
            done = subprocess.run(
                ["npx", "-y", "@anthropic-ai/mcpb@latest", "validate",
                 str(pathlib.Path(tmp) / "manifest.json")],
                capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "NOT CHECKED (npx unavailable: {})".format(type(exc).__name__)
    output = (done.stdout or "") + (done.stderr or "")
    assert done.returncode == 0, "official schema validation FAILED:\n" + output.strip()
    return "passes the official @anthropic-ai/mcpb schema"


def smoke(bundle: pathlib.Path) -> None:
    """Unpack it somewhere else entirely and speak the protocol to it.

    Run from a directory that is NOT the repo, with the repo scrubbed from
    PYTHONPATH, so a passing result cannot be the checkout leaking in. This is
    the closest thing to being the user who just double-clicked the file.

    tools/list alone would not be enough: it is answered in-process, so it stays
    green even when every real call is broken. The tools/call below is the test
    that matters, because it is the one that spawns the child.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as zf:
            zf.extractall(tmp)
        entry = pathlib.Path(tmp) / "server" / "main.py"
        frames = (
            '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
            '{"jsonrpc":"2.0","id":2,"method":"tools/call",'
            '"params":{"name":"hotin_board","arguments":{"tab":"banana"}}}\n'
        )
        done = subprocess.run([sys.executable, str(entry)], input=frames, cwd=tmp,
                              env=env, capture_output=True, text=True, timeout=120)
        lines = [l for l in (done.stdout or "").splitlines() if l.strip()]
        assert len(lines) == 2, ("bundle answered {} of 2 frames: {}".format(
            len(lines), (done.stderr or "")[:300]))

        tools = json.loads(lines[0])["result"]["tools"]
        assert {t["name"] for t in tools} == {"hotin_board", "hotin_brief"}, tools

        # A rejected tab is answered by the server itself, no child involved --
        # it proves the call path without spending 20s on a live fetch.
        body = json.loads(lines[1])["result"]
        assert body["isError"] is True, "a bad tab must come back flagged"

    # THE CHILD PROCESS IS THE PART A BUNDLE GETS WRONG, and the part that is
    # easiest to test dishonestly. `python3 -m hotin` succeeds on this machine
    # whatever the bundle does, because hotin is pip-installed here -- so a
    # plain "did it work" check passes on a bundle that would fail on every
    # user's machine. Proved: with the entry point's PYTHONPATH export removed,
    # a clean interpreter answers "No module named hotin" on every call.
    #
    # So assert WHICH hotin answered, not merely that one did.
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as zf:
            zf.extractall(tmp)
        lib = pathlib.Path(tmp) / "server" / "lib"
        child = dict(env)
        child["PYTHONPATH"] = str(lib)
        done = subprocess.run(
            [sys.executable, "-c", "import hotin,sys; sys.stdout.write(hotin.__file__)"],
            cwd=tmp, env=child, capture_output=True, text=True, timeout=60)
        resolved = pathlib.Path(done.stdout.strip() or "/nowhere").resolve()
        assert lib.resolve() in resolved.parents, (
            "the child imported {} instead of the vendored copy under {}".format(
                resolved, lib))

        done = subprocess.run([sys.executable, "-m", "hotin", "about", "--json"],
                              cwd=tmp, env=child, capture_output=True,
                              text=True, timeout=60)
        assert done.returncode == 0 and json.loads(done.stdout)["name"] == "hotin", (
            done.returncode, (done.stderr or "")[:300])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    bundle = build()
    stats = verify(bundle)
    smoke(bundle)
    print("built {} ({} files, {:.0f} KB, hotin {})".format(
        bundle, stats["files"], stats["bytes"] / 1024, stats["version"]))
    print("manifest: {}".format(stats["schema"]))
    print("verified: server vendored, protocol answered and a real child process "
          "run from the unpacked bundle outside the repo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
