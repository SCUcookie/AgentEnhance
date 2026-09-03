#!/usr/bin/env bash
set -euo pipefail

: "${AGENT_ENHANCE_REMOTE_ROOT:?set AGENT_ENHANCE_REMOTE_ROOT}"
: "${RUN_ID:?set RUN_ID}"

case "${AGENT_ENHANCE_REMOTE_ROOT}" in
  /data1/*/AgentEnhance|/data2/*/AgentEnhance) ;;
  *) echo "refusing non-project remote root" >&2; exit 2 ;;
esac

source_root="${AGENT_ENHANCE_REMOTE_ROOT}/third_party/${RUN_ID}"
run_root="${AGENT_ENHANCE_REMOTE_ROOT}/runs/${RUN_ID}"

if [[ -e "${source_root}" || -e "${run_root}" ]]; then
  echo "refusing existing R0 root" >&2
  exit 3
fi

mkdir -p "${source_root}" "${run_root}/logs" "${run_root}/evidence"
started_at="$(date -Is)"

clone_at_commit() {
  local name="$1"
  local url="$2"
  local commit="$3"
  local target="${source_root}/${name}"
  local log="${run_root}/logs/${name}.log"

  git -c advice.detachedHead=false clone --filter=blob:none --no-tags "${url}" "${target}" >"${log}" 2>&1
  git -C "${target}" checkout --detach "${commit}" >>"${log}" 2>&1
  actual="$(git -C "${target}" rev-parse HEAD)"
  if [[ "${actual}" != "${commit}" ]]; then
    echo "commit mismatch for ${name}: ${actual}" >&2
    exit 4
  fi
  git -C "${target}" status --porcelain >>"${log}"
  du -sb "${target}" >"${run_root}/evidence/${name}.bytes"
  printf '%s\t%s\t%s\n' "${name}" "${commit}" "${url}" >>"${run_root}/evidence/upstream-commits.tsv"
}

clone_at_commit mem-gallery https://github.com/YuanchenBei/Mem-Gallery.git a93959e1e978a6a7d77798ae92c2ffe41c538c62
clone_at_commit v-mem https://github.com/Dingyi-Kang/V-Mem.git 36916b14dc5241e04acbf5cd0f3c40799bc09550
clone_at_commit worldmemarena https://github.com/UCSB-AI/WorldMemArena.git 15ea25b723d9c4fb35e8062037aec6a5601e4442
clone_at_commit m2a https://github.com/Little-Fridge/M2A.git edd8c3b75bae8b2c9c1a0ac8ed67e38c2c2723f8
clone_at_commit cmi https://github.com/Saksham4796/causal-memory-intervention.git 65a66cb4347aeeb62a870132269e8a983211e036
clone_at_commit mm-mem https://github.com/EliSpectre/MM-Mem.git 7a5e214c14dd5d9c4bb9e2fca7ae12948d49b4e8
clone_at_commit m3-agent https://github.com/ByteDance-Seed/m3-agent.git 0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c
clone_at_commit mirix https://github.com/Mirix-AI/MIRIX.git 8cb06a62bbb7c478beb33dd4f2815696a72df482
clone_at_commit a-mem https://github.com/agiresearch/A-mem.git ceffb860f0712bbae97b184d440df62bc910ca8d
clone_at_commit memoryos https://github.com/BAI-LAB/MemoryOS.git 587ed7755c7aed179965792830ff1b5ad9a6fa92
clone_at_commit memengine https://github.com/nuster1128/MemEngine.git 67e779ee97599304815a0a820ca7e2e7c8ac18ea
clone_at_commit mma https://github.com/AIGeeksGroup/MMA.git 5398392340b5ff856ad3cf6ed13f9e7b05a524dd

finished_at="$(date -Is)"
printf 'run_id\tstarted_at\tfinished_at\n%s\t%s\t%s\n' "${RUN_ID}" "${started_at}" "${finished_at}" >"${run_root}/evidence/timing.tsv"
find "${run_root}" -type f ! -path "${run_root}/evidence/SHA256SUMS" -print0 | sort -z | xargs -0 sha256sum >"${run_root}/evidence/SHA256SUMS"
touch "${run_root}/TERMINAL_ACCEPTED"
