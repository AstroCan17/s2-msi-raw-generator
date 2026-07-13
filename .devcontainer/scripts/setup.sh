#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
pip install -e ".[read,dev]"

bash .devcontainer/scripts/fetch-input-data.sh
