#!/usr/bin/env bash
set -euo pipefail

bash .devcontainer/scripts/inject-rclone-config.sh
bash .devcontainer/scripts/verify-rclone.sh

python -m pip install --upgrade pip
pip install -e ".[read,dev]"
