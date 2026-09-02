#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <https-url> </data1-or-data2/final-file> [rate-limit]" >&2
  exit 64
}

[[ $# -ge 2 && $# -le 3 ]] || usage
url=$1
final_file=$2
rate_limit=${3:-20M}

[[ "$url" =~ ^https:// ]] || { echo "URL must use HTTPS" >&2; exit 65; }
[[ "$final_file" =~ ^/data[12]/[A-Za-z0-9._/-]+$ ]] || {
  echo "final path must be below /data1 or /data2" >&2
  exit 65
}
[[ ! -e "$final_file" ]] || { echo "refusing to overwrite: $final_file" >&2; exit 73; }

parent=${final_file%/*}
partial="${final_file}.partial"
mkdir -p "$parent"
curl --fail --location --retry 12 --retry-all-errors --retry-delay 10 \
  --continue-at - --limit-rate "$rate_limit" --output "$partial" "$url"
sha256=$(sha256sum -- "$partial" | awk '{print $1}')
bytes=$(stat -c '%s' "$partial")
mv -- "$partial" "$final_file"
printf '{"schema_version":"http_download_report.v1","status":"published","bytes":%s,"sha256":"%s","url":"%s"}\n' \
  "$bytes" "$sha256" "$url"
