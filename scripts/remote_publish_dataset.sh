#!/usr/bin/env bash
set -euo pipefail

: "${DATASET_ARCHIVE:?set DATASET_ARCHIVE}"
: "${FINAL_DATASET_ROOT:?set FINAL_DATASET_ROOT}"
: "${VERIFY_SCRIPT:?set VERIFY_SCRIPT}"
: "${EXPECTED_ARCHIVE_SHA256:?set EXPECTED_ARCHIVE_SHA256}"
: "${EXPECTED_MANIFEST_SHA256:?set EXPECTED_MANIFEST_SHA256}"

case "${DATASET_ARCHIVE}" in
  /data1/*/AgentEnhance/incoming/*.tar|/data2/*/AgentEnhance/incoming/*.tar) ;;
  *) echo "refusing unexpected dataset archive" >&2; exit 2 ;;
esac
case "${FINAL_DATASET_ROOT}" in
  /data1/*/AgentEnhance/datasets/raw/worldmemarena/*|/data2/*/AgentEnhance/datasets/raw/worldmemarena/*) ;;
  *) echo "refusing unexpected final dataset root" >&2; exit 2 ;;
esac
case "${VERIFY_SCRIPT}" in
  /data1/*/AgentEnhance/incoming/*.py|/data2/*/AgentEnhance/incoming/*.py) ;;
  *) echo "refusing unexpected verifier path" >&2; exit 2 ;;
esac
[[ "${EXPECTED_ARCHIVE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid archive SHA-256" >&2; exit 2; }
[[ "${EXPECTED_MANIFEST_SHA256}" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid manifest SHA-256" >&2; exit 2; }

test -f "${DATASET_ARCHIVE}"
test -f "${VERIFY_SCRIPT}"
test ! -e "${FINAL_DATASET_ROOT}"
actual_archive_sha=$(sha256sum -- "${DATASET_ARCHIVE}" | awk '{print $1}')
[[ "${actual_archive_sha}" == "${EXPECTED_ARCHIVE_SHA256}" ]] || {
  echo "archive SHA-256 mismatch" >&2; exit 3;
}

staging_root="${FINAL_DATASET_ROOT}.staging-${EXPECTED_ARCHIVE_SHA256:0:16}"
test ! -e "${staging_root}"
mkdir -p "$(dirname "${FINAL_DATASET_ROOT}")"
mkdir "${staging_root}"
tar -xf "${DATASET_ARCHIVE}" -C "${staging_root}"
python3 "${VERIFY_SCRIPT}" "${staging_root}"

actual_manifest_sha=$(sha256sum -- "${staging_root}/dataset-manifest.json" | awk '{print $1}')
[[ "${actual_manifest_sha}" == "${EXPECTED_MANIFEST_SHA256}" ]] || {
  echo "manifest SHA-256 mismatch after extraction" >&2; exit 3;
}
test ! -e "${FINAL_DATASET_ROOT}"
mv -- "${staging_root}" "${FINAL_DATASET_ROOT}"

printf '{"schema_version":"agentenhance.dataset_publish_report.v1","status":"PUBLISHED","archive_sha256":"%s","manifest_sha256":"%s","final_dataset_root":"%s"}\n' \
  "${actual_archive_sha}" "${actual_manifest_sha}" "${FINAL_DATASET_ROOT}"
