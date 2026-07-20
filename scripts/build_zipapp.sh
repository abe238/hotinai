#!/usr/bin/env sh
set -eu

python_bin="${PYTHON_BIN:-python3}"
mkdir -p dist
"$python_bin" -m zipapp src -m hotin.cli:main -o dist/hotin.pyz
