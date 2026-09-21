#!/usr/bin/env bash
set -euo pipefail

if command -v rclone >/dev/null 2>&1; then
  echo "rclone already installed: $(rclone version | head -1)"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq rclone

echo "Installed: $(rclone version | head -1)"
