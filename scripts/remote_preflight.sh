#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "usage: $0 <ssh-alias>" >&2
  exit 64
fi

ssh_target=$1
ssh "$ssh_target" '
set -eu
echo "== identity =="
hostname
date -Is
echo "== storage =="
df -h /data1 /data2
echo "== gpu inventory =="
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader
echo "== compute processes =="
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits || true
echo "== runtime =="
python3 --version || true
git --version || true
'
