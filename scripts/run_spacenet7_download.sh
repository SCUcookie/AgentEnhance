#!/usr/bin/env bash
set -euo pipefail

root=/data1/2026/ldh/AgentEnhance
downloader="$root/incoming/download_http_resumable.sh"
url=https://spacenet-dataset.s3.amazonaws.com/spacenet/SN7_buildings/tarballs/SN7_buildings_train.tar.gz
final_file="$root/datasets/raw/spacenet7/SN7_buildings_train.tar.gz"
expected_bytes=9161814623

[[ -x "$downloader" ]] || { echo "missing downloader: $downloader" >&2; exit 66; }
[[ "$(sha256sum "$downloader" | cut -d ' ' -f 1)" == cc37a2092a21b4726fe7f0ad8d654cd3cc30e8c915f5a345b00a4a684972cd28 ]] || {
  echo "downloader SHA-256 mismatch" >&2
  exit 74
}

if [[ ! -f "$final_file" ]]; then
  "$downloader" "$url" "$final_file" 20M
fi

actual_bytes=$(stat -c %s "$final_file")
[[ "$actual_bytes" == "$expected_bytes" ]] || {
  echo "SpaceNet 7 archive size mismatch: expected $expected_bytes, got $actual_bytes" >&2
  exit 74
}
sha256sum "$final_file"
chmod a-w "$final_file"
printf '{"schema_version":"dataset_archive_materialization.v1","status":"complete","bytes":%s}\n' "$actual_bytes"
