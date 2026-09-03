#!/usr/bin/env bash
set -euo pipefail

: "${INTEGRATION_ROOT:?set INTEGRATION_ROOT to a fresh project-owned run root}"
: "${PACKAGE_ROOT:?set PACKAGE_ROOT}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

case "${INTEGRATION_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected integration root" >&2; exit 2 ;;
esac
case "${PACKAGE_ROOT}" in
  /data1/*/AgentEnhance/incoming/*|/data2/*/AgentEnhance/incoming/*) ;;
  *) echo "refusing unexpected package root" >&2; exit 2 ;;
esac
[[ ! -e "${INTEGRATION_ROOT}" ]] || { echo "refusing existing integration root" >&2; exit 3; }
(
  cd "${PACKAGE_ROOT}"
  sha256sum -c PACKAGE_SHA256SUMS
)

start_services="${PACKAGE_ROOT}/inputs/scripts/remote_start_wma_services.sh"
stop_services="${PACKAGE_ROOT}/inputs/scripts/remote_stop_wma_services.sh"
unit_script="${PACKAGE_ROOT}/inputs/scripts/remote_wma_one_shot_unit_v2.sh"
seeded_launcher="${PACKAGE_ROOT}/inputs/scripts/run_wma_seeded.py"
simplemem_overlay="${PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/simplemem_overlay"
vilomem_overlay="${PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/vilomem_overlay"
service_root="${INTEGRATION_ROOT}/services"
unit_root="${INTEGRATION_ROOT}/unit-mmfu-sample100-seed0"
chat_session=agentenhance-wma-chat-fullint-r1
embed1024_session=agentenhance-wma-e1024-fullint-r1
embed384_session=agentenhance-wma-e384-fullint-r1

mkdir -p "${INTEGRATION_ROOT}/evidence"
services_started=0
terminalize() {
  local code=$?
  if (( services_started == 1 )); then
    SERVICE_RUN_ROOT="${service_root}" \
    CHAT_SESSION="${chat_session}" \
    EMBED1024_SESSION="${embed1024_session}" \
    EMBED384_SESSION="${embed384_session}" \
      bash "${stop_services}" >>"${INTEGRATION_ROOT}/integration.log" 2>&1 || true
  fi
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" \
      >"${INTEGRATION_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminalize EXIT

printf 'started_at=%s\nclaim_scope=technical integration only\nbaseline=MMFU_Single\nsample_index=100\nseed=0\n' \
  "$(date -Is)" >"${INTEGRATION_ROOT}/evidence/identity.txt"
SERVICE_RUN_ROOT="${service_root}" \
CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
EMBED_MODEL_PATH="${EMBED_MODEL_PATH}" \
CHAT_SESSION="${chat_session}" \
EMBED1024_SESSION="${embed1024_session}" \
EMBED384_SESSION="${embed384_session}" \
CHAT_MAX_MODEL_LEN=131072 \
CHAT_MAX_NUM_SEQS=1 \
CHAT_GPU_MEMORY_UTILIZATION=0.95 \
  bash "${start_services}" >"${INTEGRATION_ROOT}/integration.log" 2>&1
services_started=1

UNIT_ROOT="${unit_root}" \
BASELINE=MMFU_Single \
SAMPLE_INDEX=100 \
SAMPLE_ID_EXPECTED=mobile_05 \
SESSION_COUNT_EXPECTED=11 \
QA_COUNT_EXPECTED=13 \
UNIT_SEED=0 \
WMA_REPO="${WMA_REPO}" \
WMA_ENV="${WMA_ENV}" \
WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
WMA_DATASET_MANIFEST_SHA256=9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb \
WMA_CONFIG_SHA256=74cc054fd3a262571d67deb61f929bca68610b67320f8ea13c6b922e0257a184 \
SIMPLEMEM_OVERLAY="${simplemem_overlay}" \
VILOMEM_OVERLAY="${vilomem_overlay}" \
WMA_SEEDED_LAUNCHER="${seeded_launcher}" \
WMA_SEEDED_LAUNCHER_SHA256=f362f371ea4bdf73f5a4ece64a524d55a27fc95147bcb87308202608de3b1064 \
  bash "${unit_script}" >>"${INTEGRATION_ROOT}/integration.log" 2>&1

SERVICE_RUN_ROOT="${service_root}" \
CHAT_SESSION="${chat_session}" \
EMBED1024_SESSION="${embed1024_session}" \
EMBED384_SESSION="${embed384_session}" \
  bash "${stop_services}" >>"${INTEGRATION_ROOT}/integration.log" 2>&1
services_started=0

test -f "${unit_root}/TERMINAL_ACCEPTED"
test ! -e "${unit_root}/TERMINAL_REJECTED"
printf 'finished_at=%s\n' "$(date -Is)" >>"${INTEGRATION_ROOT}/evidence/identity.txt"
find "${INTEGRATION_ROOT}" -type f ! -name SHA256SUMS ! -name 'TERMINAL_*' -print0 \
  | sort -z | xargs -0 sha256sum >"${INTEGRATION_ROOT}/SHA256SUMS"
touch "${INTEGRATION_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
printf 'TERMINAL_ACCEPTED full-stack integration\n'
