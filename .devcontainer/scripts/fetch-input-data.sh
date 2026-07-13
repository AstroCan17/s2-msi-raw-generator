#!/usr/bin/env bash
set -euo pipefail

DATA_REPO_OWNER="${DATA_REPO_OWNER:-AstroCan17}"
DATA_REPO_NAME="${DATA_REPO_NAME:-s2-msi-raw-generator-data}"
DATASET_TAG="${DATASET_TAG:-datasets-v1}"
DATASET_ASSET_NAME="${DATASET_ASSET_NAME:-input-data.tar.gz}"
DATA_DIR="${DATA_DIR:-data}"
FORCE_DATA_SYNC="${FORCE_DATA_SYNC:-0}"

if [[ -z "${DATA_REPO_PAT:-}" ]]; then
  echo "ERROR: DATA_REPO_PAT is not set. Configure it in Codespaces Secrets."
  exit 1
fi

if [[ "${FORCE_DATA_SYNC}" != "1" && -f "${DATA_DIR}/.dataset_tag" ]]; then
  CURRENT_TAG="$(cat "${DATA_DIR}/.dataset_tag")"
  if [[ "${CURRENT_TAG}" == "${DATASET_TAG}" ]]; then
    echo "Dataset already present for tag ${DATASET_TAG}. Skipping download."
    exit 0
  fi
fi

RELEASE_API_URL="https://api.github.com/repos/${DATA_REPO_OWNER}/${DATA_REPO_NAME}/releases/tags/${DATASET_TAG}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

RELEASE_JSON="${TMP_DIR}/release.json"
DATA_ARCHIVE="${TMP_DIR}/${DATASET_ASSET_NAME}"
SHA_FILE="${TMP_DIR}/${DATASET_ASSET_NAME}.sha256"

curl -fsSL \
  -H "Authorization: Bearer ${DATA_REPO_PAT}" \
  -H "Accept: application/vnd.github+json" \
  "${RELEASE_API_URL}" \
  -o "${RELEASE_JSON}"

ASSET_ID="$(
python - "${RELEASE_JSON}" "${DATASET_ASSET_NAME}" <<'PY'
import json
import sys

path, wanted = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
for asset in payload.get("assets", []):
    if asset.get("name") == wanted:
        print(asset["id"])
        break
PY
)"

if [[ -z "${ASSET_ID}" ]]; then
  echo "ERROR: Asset '${DATASET_ASSET_NAME}' not found in release tag '${DATASET_TAG}'."
  exit 1
fi

ASSET_API_URL="https://api.github.com/repos/${DATA_REPO_OWNER}/${DATA_REPO_NAME}/releases/assets/${ASSET_ID}"

curl -fsSL \
  -H "Authorization: Bearer ${DATA_REPO_PAT}" \
  -H "Accept: application/octet-stream" \
  "${ASSET_API_URL}" \
  -o "${DATA_ARCHIVE}"

SHA_ASSET_ID="$(
python - "${RELEASE_JSON}" "${DATASET_ASSET_NAME}.sha256" <<'PY'
import json
import sys

path, wanted = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
for asset in payload.get("assets", []):
    if asset.get("name") == wanted:
        print(asset["id"])
        break
PY
)"

if [[ -n "${SHA_ASSET_ID}" ]]; then
  SHA_ASSET_API_URL="https://api.github.com/repos/${DATA_REPO_OWNER}/${DATA_REPO_NAME}/releases/assets/${SHA_ASSET_ID}"
  curl -fsSL \
    -H "Authorization: Bearer ${DATA_REPO_PAT}" \
    -H "Accept: application/octet-stream" \
    "${SHA_ASSET_API_URL}" \
    -o "${SHA_FILE}"
  (cd "${TMP_DIR}" && sha256sum -c "${SHA_FILE}")
else
  echo "WARN: ${DATASET_ASSET_NAME}.sha256 not found in release. Skipping checksum validation."
fi

mkdir -p "${DATA_DIR}"
tar -xzf "${DATA_ARCHIVE}" -C "${DATA_DIR}"
printf '%s\n' "${DATASET_TAG}" > "${DATA_DIR}/.dataset_tag"

if [[ -z "${S2_DATA_STORE:-}" ]]; then
  export S2_DATA_STORE="${DATA_DIR}"
fi

echo "Input data fetched and extracted to ${DATA_DIR}/ (tag: ${DATASET_TAG})."
echo "Set S2_DATA_STORE=${S2_DATA_STORE} for pipeline runs."
