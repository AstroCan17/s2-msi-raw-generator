#!/usr/bin/env bash
set -euo pipefail

DATA_REPO_OWNER="${DATA_REPO_OWNER:-AstroCan17}"
DATA_REPO_NAME="${DATA_REPO_NAME:-s2-msi-raw-generator-data}"
DATASET_TAG="${DATASET_TAG:-datasets-v1}"
DATASET_ASSET_NAME="${DATASET_ASSET_NAME:-}"
DATASET_ASSETS="${DATASET_ASSETS:-input-data-core.tar.gz input-data-public.tar.gz}"
DATA_DIR="${DATA_DIR:-data}"
FORCE_DATA_SYNC="${FORCE_DATA_SYNC:-0}"
GITHUB_MAX_BYTES=$((2 * 1024 * 1024 * 1024))

if [[ -z "${DATA_REPO_PAT:-}" ]]; then
  echo "ERROR: DATA_REPO_PAT is not set. Configure it in Codespaces Secrets."
  exit 1
fi

if [[ -n "${DATASET_ASSET_NAME}" ]]; then
  ASSETS=("${DATASET_ASSET_NAME}")
else
  read -r -a ASSETS <<< "${DATASET_ASSETS}"
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
curl -fsSL \
  -H "Authorization: Bearer ${DATA_REPO_PAT}" \
  -H "Accept: application/vnd.github+json" \
  "${RELEASE_API_URL}" \
  -o "${RELEASE_JSON}"

asset_id() {
  python - "${RELEASE_JSON}" "$1" <<'PY'
import json, sys
path, wanted = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    payload = json.load(f)
for asset in payload.get("assets", []):
    if asset.get("name") == wanted:
        print(asset["id"])
        break
PY
}

download_asset() {
  local name="$1"
  local dest="$2"
  local id
  id="$(asset_id "${name}")"
  if [[ -z "${id}" ]]; then
    echo "ERROR: Asset '${name}' not found in release tag '${DATASET_TAG}'."
    exit 1
  fi
  curl -fsSL \
    -H "Authorization: Bearer ${DATA_REPO_PAT}" \
    -H "Accept: application/octet-stream" \
    "https://api.github.com/repos/${DATA_REPO_OWNER}/${DATA_REPO_NAME}/releases/assets/${id}" \
    -o "${dest}"
}

mkdir -p "${DATA_DIR}"

for asset_name in "${ASSETS[@]}"; do
  archive="${TMP_DIR}/${asset_name}"
  download_asset "${asset_name}" "${archive}"

  sha_name="${asset_name}.sha256"
  sha_id="$(asset_id "${sha_name}")"
  if [[ -n "${sha_id}" ]]; then
    sha_file="${TMP_DIR}/${sha_name}"
    curl -fsSL \
      -H "Authorization: Bearer ${DATA_REPO_PAT}" \
      -H "Accept: application/octet-stream" \
      "https://api.github.com/repos/${DATA_REPO_OWNER}/${DATA_REPO_NAME}/releases/assets/${sha_id}" \
      -o "${sha_file}"
    (cd "${TMP_DIR}" && sha256sum -c "${sha_name}")
  else
    echo "WARN: ${sha_name} not found. Skipping checksum validation for ${asset_name}."
  fi

  tar -xzf "${archive}" -C "${DATA_DIR}"
  echo "Extracted ${asset_name} → ${DATA_DIR}/"
done

printf '%s\n' "${DATASET_TAG}" > "${DATA_DIR}/.dataset_tag"

if [[ -z "${S2_DATA_STORE:-}" ]]; then
  export S2_DATA_STORE="${DATA_DIR}"
fi

echo "Input data fetched and extracted to ${DATA_DIR}/ (tag: ${DATASET_TAG})."
echo "Set S2_DATA_STORE=${S2_DATA_STORE} for pipeline runs."
