#!/usr/bin/env bash
# Post-create smoke: binary + config + remote API reachability only.
# Does NOT copy, sync, or mount any dataset (no multi-GB transfers).
set -euo pipefail

CONF_FILE="${HOME}/.config/rclone/rclone.conf"
RCLONE_FLAGS=(--retries 1 --low-level-retries 1 --timeout 30s)

if [[ ! -f "${CONF_FILE}" ]]; then
  if [[ "${VERIFY_RCLONE_REQUIRED:-0}" == "1" ]]; then
    echo "verify-rclone: FAIL — RCLONE_CONF_B64 secret missing or empty" >&2
    exit 1
  fi
  echo "verify-rclone: SKIP (no config — secret not set)"
  exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "verify-rclone: FAIL — rclone binary missing" >&2
  exit 1
fi

mapfile -t remotes < <(rclone "${RCLONE_FLAGS[@]}" listremotes)
if [[ ${#remotes[@]} -eq 0 ]]; then
  echo "verify-rclone: FAIL — rclone.conf has no remotes" >&2
  exit 1
fi

echo "verify-rclone: remotes — ${remotes[*]}"

# Metadata-only API call (quota/usage); no file bodies transferred.
first_remote="${remotes[0]}"
rclone "${RCLONE_FLAGS[@]}" about "${first_remote}" --json >/dev/null

echo "verify-rclone: OK (${first_remote} API reachable, zero dataset bytes transferred)"
