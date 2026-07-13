#!/usr/bin/env bash
# Build the split s2-msi-raw-generator dataset release (fits GitHub 2 GiB/asset limit).
set -euo pipefail

DATA_REPO_OWNER="${DATA_REPO_OWNER:-AstroCan17}"
DATA_REPO_NAME="${DATA_REPO_NAME:-s2-msi-raw-generator-data}"
DATASET_TAG="${DATASET_TAG:-datasets-v1}"
GIPP_SRC="${GIPP_SRC:-/home/cando/Development/cdk-cosmic/04-projects/eopf-data-download-jupyter/ACT/DATA/GIPP}"
STORE_SRC="${STORE_SRC:-/home/cando/Development/cdk-cosmic/04-projects/02-gitlab/data-store-database/msi-processor}"
GITHUB_MAX_BYTES=$((2 * 1024 * 1024 * 1024))

for required in "$GIPP_SRC" "$STORE_SRC/inputs/PDI_MSI_S2_L1A.zarr" "$STORE_SRC/inputs/public-data"; do
  if [[ ! -e "$required" ]]; then
    echo "ERROR: missing source path: $required"
    exit 1
  fi
done

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

stage_and_archive() {
  local asset_name="$1"
  local stage="$2"
  shift 2
  mkdir -p "$stage"
  for src in "$@"; do
    local dest="$stage/$(basename "$src")"
  if [[ -d "$src" && "$src" == */inputs/* ]]; then
      dest="$stage/inputs/$(basename "$src")"
      mkdir -p "$stage/inputs"
    elif [[ "$(basename "$(dirname "$src")")" == "s2-sensor" || "$src" == *GIPP ]]; then
      mkdir -p "$stage/inputs/s2-sensor"
      dest="$stage/inputs/s2-sensor/GIPP"
    fi
    cp -a "$src" "$dest"
  done
  local archive="${TMP_DIR}/${asset_name}"
  tar -czf "${archive}" -C "${stage}" .
  ( cd "${TMP_DIR}" && sha256sum "${asset_name}" > "${asset_name}.sha256" )
  local bytes
  bytes="$(stat -c%s "${archive}")"
  if (( bytes > GITHUB_MAX_BYTES )); then
    echo "ERROR: ${asset_name} is ${bytes} bytes (> 2 GiB)"
    exit 1
  fi
  echo "Built ${asset_name} ($(du -h "${archive}" | cut -f1))"
}

CORE_STAGE="${TMP_DIR}/core-stage"
mkdir -p "${CORE_STAGE}/inputs/s2-sensor"
cp -a "${GIPP_SRC}" "${CORE_STAGE}/inputs/s2-sensor/GIPP"
cp -a "${STORE_SRC}/inputs/PDI_MSI_S2_L1A.zarr" "${CORE_STAGE}/inputs/"
cp -a "${STORE_SRC}/inputs/real_l0" "${CORE_STAGE}/inputs/"
tar -czf "${TMP_DIR}/input-data-core.tar.gz" -C "${CORE_STAGE}" .
( cd "${TMP_DIR}" && sha256sum input-data-core.tar.gz > input-data-core.tar.gz.sha256 )

PUBLIC_STAGE="${TMP_DIR}/public-stage"
mkdir -p "${PUBLIC_STAGE}/inputs"
cp -a "${STORE_SRC}/inputs/public-data" "${PUBLIC_STAGE}/inputs/"
tar -czf "${TMP_DIR}/input-data-public.tar.gz" -C "${PUBLIC_STAGE}" .
( cd "${TMP_DIR}" && sha256sum input-data-public.tar.gz > input-data-public.tar.gz.sha256 )

for asset in input-data-core.tar.gz input-data-public.tar.gz; do
  bytes="$(stat -c%s "${TMP_DIR}/${asset}")"
  if (( bytes > GITHUB_MAX_BYTES )); then
    echo "ERROR: ${asset} exceeds GitHub 2 GiB limit (${bytes} bytes)"
    exit 1
  fi
  echo "Built ${asset} ($(du -h "${TMP_DIR}/${asset}" | cut -f1))"
done

NOTES_FILE="${TMP_DIR}/release-notes.md"
cat > "${NOTES_FILE}" <<EOF
Split dataset release \`${DATASET_TAG}\` for s2-msi-raw-generator.

Assets:
- \`input-data-core.tar.gz\` — GIPP, L1A zarr, real_l0
- \`input-data-public.tar.gz\` — public L0 validation products
- matching \`.sha256\` files
EOF

if gh release view "${DATASET_TAG}" --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" >/dev/null 2>&1; then
  gh release upload "${DATASET_TAG}" \
    "${TMP_DIR}/input-data-core.tar.gz" "${TMP_DIR}/input-data-core.tar.gz.sha256" \
    "${TMP_DIR}/input-data-public.tar.gz" "${TMP_DIR}/input-data-public.tar.gz.sha256" \
    --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" --clobber
else
  gh release create "${DATASET_TAG}" \
    "${TMP_DIR}/input-data-core.tar.gz" "${TMP_DIR}/input-data-core.tar.gz.sha256" \
    "${TMP_DIR}/input-data-public.tar.gz" "${TMP_DIR}/input-data-public.tar.gz.sha256" \
    --repo "${DATA_REPO_OWNER}/${DATA_REPO_NAME}" \
    --title "Dataset ${DATASET_TAG}" \
    --notes-file "${NOTES_FILE}"
fi

echo "Published split ${DATASET_TAG} to ${DATA_REPO_OWNER}/${DATA_REPO_NAME}"
