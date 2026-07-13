#!/usr/bin/env bash
set -euo pipefail

CONF_DIR="${HOME}/.config/rclone"
CONF_FILE="${CONF_DIR}/rclone.conf"

# Raw rclone.conf pasted into Codespaces secret (no base64). RCLONE_CONF_B64 kept for
# the secret name already configured in GitHub; RCLONE_CONF is an alias.
RCLONE_CONF_CONTENT="${RCLONE_CONF:-${RCLONE_CONF_B64:-}}"

if [[ -z "${RCLONE_CONF_CONTENT}" ]]; then
  echo "WARNING: RCLONE_CONF (or RCLONE_CONF_B64) is not set; rclone config not injected."
  echo "Paste the full contents of ~/.config/rclone/rclone.conf into Codespaces secrets."
  exit 0
fi

mkdir -p "${CONF_DIR}"
umask 077
printf '%s\n' "${RCLONE_CONF_CONTENT}" > "${CONF_FILE}"
chmod 600 "${CONF_FILE}"
echo "rclone config injected at ${CONF_FILE}"
