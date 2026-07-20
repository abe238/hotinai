#!/usr/bin/env sh
# Builds a single-file dist/hotin.pyz from the real package source (never hand-maintained,
# regenerated from src/hotin/ every time so it can't drift from the real code).
set -eu

python_bin="${PYTHON_BIN:-python3}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$repo_root/dist"

# zipapp's own -m flag generates a __main__.py that calls main() WITHOUT sys.exit(), so a
# command's real exit code (e.g. 2 for bad usage) is silently dropped and the process always
# exits 0. Write a real __main__.py ourselves instead, in a clean staging copy of the package
# (excluding __pycache__/egg-info so the archive isn't bloated with local build artifacts).
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

cp -R "$repo_root/src/hotin" "$stage/hotin"
find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$stage" -name '*.egg-info' -type d -prune -exec rm -rf {} +

cat > "$stage/__main__.py" <<'PYEOF'
import sys

from hotin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
PYEOF

"$python_bin" -m zipapp "$stage" -o "$repo_root/dist/hotin.pyz"
