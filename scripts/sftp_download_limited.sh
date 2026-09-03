#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <ssh-alias> </data1-or-data2/remote-file> <local-file> [rate-kbit-per-second]" >&2
  exit 64
}

[[ $# -ge 3 && $# -le 4 ]] || usage

ssh_target=$1
remote_file=$2
local_file=$3
rate_limit=${4:-4096}

[[ "$ssh_target" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "unsafe SSH alias" >&2; exit 65; }
[[ "$remote_file" =~ ^/data[12]/[A-Za-z0-9._/-]+$ ]] || {
  echo "remote path must be a simple absolute path below /data1 or /data2" >&2
  exit 65
}
[[ "$rate_limit" =~ ^[1-9][0-9]*$ ]] || { echo "rate limit must be a positive integer in Kbit/s" >&2; exit 65; }

local_parent=$(cd "$(dirname "$local_file")" && pwd -P)
local_target="$local_parent/$(basename "$local_file")"
[[ ! -e "$local_target" ]] || { echo "local target already exists: $local_target" >&2; exit 73; }
[[ "$local_target" != *'"'* && "$local_target" != *$'\n'* && "$local_target" != *$'\r'* ]] || {
  echo "local path contains unsupported characters" >&2
  exit 65
}

remote_sha=$(ssh "$ssh_target" "test -f '$remote_file'; sha256sum -- '$remote_file' | awk '{print \$1}'")
partial_file="${local_target}.partial.${remote_sha:0:16}"
batch_file=$(mktemp "${TMPDIR:-/tmp}/agent-enhance-sftp-download.XXXXXX")
cleanup() {
  rm -f "$batch_file"
}
trap cleanup EXIT INT TERM

local_sha=""
if [[ -f "$partial_file" ]]; then
  if command -v shasum >/dev/null 2>&1; then
    local_sha=$(shasum -a 256 "$partial_file" | awk '{print $1}')
  else
    local_sha=$(sha256sum "$partial_file" | awk '{print $1}')
  fi
fi
if [[ "$local_sha" != "$remote_sha" ]]; then
  if [[ -f "$partial_file" ]]; then
    printf 'reget -p "%s" "%s"\n' "$remote_file" "$partial_file" >"$batch_file"
  else
    printf 'get -p "%s" "%s"\n' "$remote_file" "$partial_file" >"$batch_file"
  fi
  sftp -q -l "$rate_limit" -b "$batch_file" "$ssh_target"
fi

if command -v shasum >/dev/null 2>&1; then
  local_sha=$(shasum -a 256 "$partial_file" | awk '{print $1}')
else
  local_sha=$(sha256sum "$partial_file" | awk '{print $1}')
fi
if [[ "$local_sha" != "$remote_sha" ]]; then
  echo "SHA-256 mismatch; partial file retained at $partial_file" >&2
  exit 74
fi
mv -- "$partial_file" "$local_target"
printf '{"schema_version":"sftp_download_report.v1","status":"published","sha256":"%s","rate_limit_kbit_per_second":%s,"local_path":"%s"}\n' \
  "$local_sha" "$rate_limit" "$local_target"
