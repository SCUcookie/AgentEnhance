#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <local-file> <ssh-alias> </data1-or-data2/remote-file> [rate-kbit-per-second]" >&2
  exit 64
}

[[ $# -ge 3 && $# -le 4 ]] || usage

local_file=$1
ssh_target=$2
remote_file=$3
rate_limit=${4:-8192}

[[ -f "$local_file" ]] || { echo "local file does not exist: $local_file" >&2; exit 66; }
[[ "$ssh_target" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "unsafe SSH alias" >&2; exit 65; }
[[ "$remote_file" =~ ^/data[12]/[A-Za-z0-9._/-]+$ ]] || {
  echo "remote path must be a simple absolute path below /data1 or /data2" >&2
  exit 65
}
[[ "$rate_limit" =~ ^[1-9][0-9]*$ ]] || { echo "rate limit must be a positive integer in Kbit/s" >&2; exit 65; }

if command -v shasum >/dev/null 2>&1; then
  local_sha=$(shasum -a 256 "$local_file" | awk '{print $1}')
else
  local_sha=$(sha256sum "$local_file" | awk '{print $1}')
fi

local_abs=$(cd "$(dirname "$local_file")" && pwd -P)/$(basename "$local_file")
[[ "$local_abs" != *'"'* && "$local_abs" != *$'\n'* && "$local_abs" != *$'\r'* ]] || {
  echo "local path contains unsupported characters" >&2
  exit 65
}

partial_file="${remote_file}.partial.${local_sha:0:16}"
remote_parent=${remote_file%/*}

ssh "$ssh_target" "test -d '$remote_parent' && test -w '$remote_parent' && test ! -e '$remote_file'"

batch_file=$(mktemp "${TMPDIR:-/tmp}/agent-enhance-sftp.XXXXXX")
cleanup() {
  rm -f "$batch_file"
}
trap cleanup EXIT INT TERM

if ssh "$ssh_target" "test -f '$partial_file'"; then
  transfer_command=reput
else
  transfer_command=put
fi
printf '%s -p "%s" "%s"\n' "$transfer_command" "$local_abs" "$partial_file" >"$batch_file"
sftp -q -l "$rate_limit" -b "$batch_file" "$ssh_target"

remote_sha=$(ssh "$ssh_target" "sha256sum -- '$partial_file' | awk '{print \$1}'")
if [[ "$remote_sha" != "$local_sha" ]]; then
  echo "SHA-256 mismatch; partial file retained at $partial_file" >&2
  exit 74
fi

ssh "$ssh_target" "set -eu; test ! -e '$remote_file'; test -f '$partial_file'; mv -- '$partial_file' '$remote_file'"
printf '{"schema_version":"sftp_upload_report.v1","status":"published","sha256":"%s","rate_limit_kbit_per_second":%s,"remote_path":"%s"}\n' \
  "$local_sha" "$rate_limit" "$remote_file"
