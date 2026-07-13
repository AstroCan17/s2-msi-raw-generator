#!/usr/bin/env bash
# Package a data-store layout directory and publish it as a GitHub Release asset.
#
# Usage:
#   DATA_REPO_NAME=s2-msi-raw-generator-data \
#     .devcontainer/scripts/publish-dataset.sh /path/to/store-root
#
# The archive root must match the pipeline store layout (inputs/, l0/, ...).
set -euo pipefail

SOURCE_DIR="${1:-}"
DATA_REPO_OWNER="${DATA_REPO_OWNER:-AstroCan17}"
DATA_REPO_NAME="${DATA_REPO_NAME:-s2-msi-raw-generator-data}"
DATASET_TAG="${DATASET_TAG:-datasets-v1}"
DATASET_ASSET_NAME="${DATASET_ASSET_NAME:-input-data.tar.gz}"
GITHUB_MAX_BYTES=$((2 * 1024 * 1024 * 1024))

if [[ -z "${SOURCE_DIR}" || ! -d "${SOURCE_DIR}" ]]; then
  echo "Usage: publish-dataset.sh <store-root-dir>"
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI is required to publish releases."
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

ARCHIVE="${TMP_DIR}/${DATASET_ASSET_NAME}"
SHA_FILE="${TMP_DIR}/${DATASET_ASSET_NAME}.sha256"

echo "Packaging ${SOURCE_DIR} → ${DATASET_ASSET_NAME}"
tar -czf "${ARCHIVE}" -C "${SOURCE_DIR}" .
( cd "${TMP_DIR}" && sha256sum "${DATASET_ASSET_NAME}" > "${DATASET_ASSET_NAME}.sha256" )

ARCHIVE_BYTES="$(stat -c%s "${ARCHIVE}")"
if (( ARCHIVE_BYTES > GITHUB_MAX_BYTES )); then
  echo "ERROR: ${DATASET_ASSET_NAME} is ${ARCHIVE_BYTES} bytes (> GitHub 2 GiB release asset limit)."
  echo "Split the store into smaller archives or prune optional layers before publishing."
  exit 1
fi

NOTES_FILE="${TMP_DIR}/release-notes.md"
cat > "${NOTES_FILE}" <<EOF
Dataset release \`${DATASET_TAG}\` for \`${DATA_REPO_OWNER}/${DATA_REPO_NAME}\`.

Assets:
- \`${DATASET_ASSET_NAME}\`
- \`${DATASET_ASSET_NAME}.sha256\`

Published by \`publish-dataset.sh\` from host \`$(hostname)\` at \`$(date -u +"%Y-%m-%dT%H:%M:%SZ")\`.
EOF

if gh release view "${DATASET_TAG}" --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" >/dev/null 2>&1; then
  echo "Release ${DATASET_TAG} exists — uploading assets"
  gh release upload "${DATASET_TAG}" \
    "${ARCHIVE}" "${SHA_FILE}" \
    --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" \
    --clobber
else
  gh release create "${DATASET_TAG}" \
    "${ARCHIVE}" "${SHA_FILE}" \
    --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" \
    --title "Dataset ${DATASET_TAG}" \
    --notes-file "${NOTES_FILE}"
fi

echo "Published ${DATASET_TAG} to ${DATA_REPO_OWNER}/${DATA_REPO_NAME}"
