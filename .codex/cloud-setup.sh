#!/usr/bin/env bash
# Minimal setup for an isolated Codex Cloud environment; no production access.
set -euo pipefail

python3 -m pip install --disable-pip-version-check -e '.[dev]'
python3 -m pip install --disable-pip-version-check 'ruff==0.16.9' 'mypy==1.18.2'

python3 -m pytest --version
ruff --version
mypy --version
