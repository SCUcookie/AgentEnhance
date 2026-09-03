#!/usr/bin/env bash
set -euo pipefail

: "${CAPABILITY_ROOT:?set CAPABILITY_ROOT to a fresh project-owned run root}"
: "${PARENT_PACKAGE_ROOT:?set PARENT_PACKAGE_ROOT}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

PACKAGE_MANIFEST_SHA256=4d3433dd616b938e431c68e807358c4d9b55719345660f3f97bae293fb5ce361
START_SHA256=0763c1c1bac4326168ec873181c037f506f41be8e50d0f242a0957aef5eb8b5b
STOP_SHA256=cc3cb31f83b5917f77831261d73602dc47cdd5e53e84b664a6e0ed45ae923ffe
UNIT_SHA256=fcff3ee9ccbcc9a58be95cbe0dd9b85ebefb30094f9c67dc97797811d1654d60
LAUNCHER_SHA256=f362f371ea4bdf73f5a4ece64a524d55a27fc95147bcb87308202608de3b1064
INVENTORY_SHA256=027f2c3f757d99cb098a6e1887ac7bc837f726031368a4c758970ee90db33f39

case "${CAPABILITY_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected capability root" >&2; exit 2 ;;
esac
case "${PARENT_PACKAGE_ROOT}" in
  /data1/*/AgentEnhance/incoming/*|/data2/*/AgentEnhance/incoming/*) ;;
  *) echo "refusing unexpected parent package root" >&2; exit 2 ;;
esac
test ! -e "${CAPABILITY_ROOT}"
[[ "$(sha256sum "${PARENT_PACKAGE_ROOT}/PACKAGE_SHA256SUMS" | awk '{print $1}')" == "${PACKAGE_MANIFEST_SHA256}" ]]
(
  cd "${PARENT_PACKAGE_ROOT}"
  sha256sum -c PACKAGE_SHA256SUMS
)

start_script="${PARENT_PACKAGE_ROOT}/inputs/scripts/remote_start_wma_services.sh"
stop_script="${PARENT_PACKAGE_ROOT}/inputs/scripts/remote_stop_wma_services.sh"
unit_script="${PARENT_PACKAGE_ROOT}/inputs/scripts/remote_wma_one_shot_unit_v2.sh"
launcher="${PARENT_PACKAGE_ROOT}/inputs/scripts/run_wma_seeded.py"
inventory="${PARENT_PACKAGE_ROOT}/inputs/comparisons/wma-small-run-units.v1.csv"
simplemem_overlay="${PARENT_PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/simplemem_overlay"
vilomem_overlay="${PARENT_PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/vilomem_overlay"
[[ "$(sha256sum "${start_script}" | awk '{print $1}')" == "${START_SHA256}" ]]
[[ "$(sha256sum "${stop_script}" | awk '{print $1}')" == "${STOP_SHA256}" ]]
[[ "$(sha256sum "${unit_script}" | awk '{print $1}')" == "${UNIT_SHA256}" ]]
[[ "$(sha256sum "${launcher}" | awk '{print $1}')" == "${LAUNCHER_SHA256}" ]]
[[ "$(sha256sum "${inventory}" | awk '{print $1}')" == "${INVENTORY_SHA256}" ]]

row=$(awk -F, '$1 == 72 {print; found++} END {if (found != 1) exit 4}' "${inventory}")
IFS=, read -r sample_index sample_id relative_json_path sessions turns attachments qa source_json_sha256 <<<"${row}"
[[ "${sample_id}" == "css_03" ]]

service_root="${CAPABILITY_ROOT}/services"
unit_root="${CAPABILITY_ROOT}/unit-072-css_03"
chat_session=agentenhance-wma-chat-oom-r2-v1
embed1024_session=agentenhance-wma-e1024-oom-r2-v1
embed384_session=agentenhance-wma-e384-oom-r2-v1
services_started=0
terminalize() {
  code=$?
  if (( services_started == 1 )); then
    SERVICE_RUN_ROOT="${service_root}" CHAT_SESSION="${chat_session}" \
    EMBED1024_SESSION="${embed1024_session}" EMBED384_SESSION="${embed384_session}" \
      bash "${stop_script}" >>"${CAPABILITY_ROOT}/capability.log" 2>&1 || true
  fi
  if (( code != 0 )) && [[ -d "${CAPABILITY_ROOT}" ]]; then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${CAPABILITY_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminalize EXIT

SERVICE_RUN_ROOT="${service_root}" CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
EMBED_MODEL_PATH="${EMBED_MODEL_PATH}" CHAT_SESSION="${chat_session}" \
EMBED1024_SESSION="${embed1024_session}" EMBED384_SESSION="${embed384_session}" \
CHAT_MAX_MODEL_LEN=131072 CHAT_MAX_NUM_SEQS=1 CHAT_GPU_MEMORY_UTILIZATION=0.90 \
  bash "${start_script}" >"${CAPABILITY_ROOT}.startup.log" 2>&1
services_started=1
mv "${CAPABILITY_ROOT}.startup.log" "${CAPABILITY_ROOT}/capability.log"

UNIT_ROOT="${unit_root}" BASELINE=MMFU_Single SAMPLE_INDEX="${sample_index}" \
SAMPLE_ID_EXPECTED="${sample_id}" SESSION_COUNT_EXPECTED="${sessions}" \
QA_COUNT_EXPECTED="${qa}" UNIT_SEED=0 WMA_REPO="${WMA_REPO}" WMA_ENV="${WMA_ENV}" \
WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
WMA_DATASET_MANIFEST_SHA256=9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb \
WMA_CONFIG_SHA256=74cc054fd3a262571d67deb61f929bca68610b67320f8ea13c6b922e0257a184 \
SIMPLEMEM_OVERLAY="${simplemem_overlay}" VILOMEM_OVERLAY="${vilomem_overlay}" \
WMA_SEEDED_LAUNCHER="${launcher}" WMA_SEEDED_LAUNCHER_SHA256="${LAUNCHER_SHA256}" \
  bash "${unit_script}" >>"${CAPABILITY_ROOT}/capability.log" 2>&1
test -f "${unit_root}/TERMINAL_ACCEPTED"
curl -fsS http://127.0.0.1:18120/v1/models >"${CAPABILITY_ROOT}/services/evidence/chat-models-after.json"
! grep -q "CUDA out of memory" "${service_root}/logs/chat.log"

SERVICE_RUN_ROOT="${service_root}" CHAT_SESSION="${chat_session}" \
EMBED1024_SESSION="${embed1024_session}" EMBED384_SESSION="${embed384_session}" \
  bash "${stop_script}" >>"${CAPABILITY_ROOT}/capability.log" 2>&1
services_started=0
cat >"${CAPABILITY_ROOT}/audit.json" <<EOF
{
  "schema_version": "agentenhance.wma_oom_capability_recovery2_audit.v1",
  "status": "TERMINAL_ACCEPTED",
  "sample_index": 72,
  "sample_id": "css_03",
  "seed": 0,
  "chat_gpu_memory_utilization": 0.90,
  "chat_max_model_len": 131072,
  "chat_max_num_seqs": 1,
  "unit_terminal_accepted": true,
  "chat_service_alive_after_unit": true,
  "cuda_oom_observed": false,
  "main_comparison_eligible": false,
  "numeric_results_admitted": false
}
EOF
find "${CAPABILITY_ROOT}" -type f ! -name SHA256SUMS ! -name 'TERMINAL_*' -print0 \
  | sort -z | xargs -0 sha256sum >"${CAPABILITY_ROOT}/SHA256SUMS"
touch "${CAPABILITY_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
printf 'OOM recovery capability accepted at %s\n' "$(date -Is)"
