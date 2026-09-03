#!/usr/bin/env bash
set -euo pipefail

: "${GATE_ROOT:?set GATE_ROOT to a fresh project-owned run directory}"
: "${START_SERVICES_SCRIPT:?set START_SERVICES_SCRIPT}"
: "${STOP_SERVICES_SCRIPT:?set STOP_SERVICES_SCRIPT}"
: "${UNIT_SCRIPT:?set UNIT_SCRIPT}"
: "${HASH_SCRIPT:?set HASH_SCRIPT}"
: "${AUDIT_SCRIPT:?set AUDIT_SCRIPT}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${SIMPLEMEM_OVERLAY:?set SIMPLEMEM_OVERLAY}"
: "${VILOMEM_OVERLAY:?set VILOMEM_OVERLAY}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

WMA_DATASET_MANIFEST_SHA256=9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb
WMA_CONFIG_SHA256=74cc054fd3a262571d67deb61f929bca68610b67320f8ea13c6b922e0257a184
SERVICE_ROOT="${GATE_ROOT}/services"
CHAT_SESSION=agentenhance-wma-chat-detgate-r1
EMBED1024_SESSION=agentenhance-wma-embed1024-detgate-r1
EMBED384_SESSION=agentenhance-wma-embed384-detgate-r1

case "${GATE_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected gate root" >&2; exit 2 ;;
esac
[[ ! -e "${GATE_ROOT}" ]] || { echo "refusing existing gate root" >&2; exit 3; }
mkdir -p "${GATE_ROOT}/semantic-digests" "${GATE_ROOT}/evidence"

services_started=0
terminalize() {
  local code=$?
  if (( services_started == 1 )); then
    SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
    CHAT_SESSION="${CHAT_SESSION}" \
    EMBED1024_SESSION="${EMBED1024_SESSION}" \
    EMBED384_SESSION="${EMBED384_SESSION}" \
      bash "${STOP_SERVICES_SCRIPT}" >>"${GATE_ROOT}/controller.log" 2>&1 || true
  fi
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${GATE_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminalize EXIT

printf 'started_at=%s\n' "$(date -Is)" >"${GATE_ROOT}/evidence/controller-timing.txt"
SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
EMBED_MODEL_PATH="${EMBED_MODEL_PATH}" \
CHAT_SESSION="${CHAT_SESSION}" \
EMBED1024_SESSION="${EMBED1024_SESSION}" \
EMBED384_SESSION="${EMBED384_SESSION}" \
CHAT_MAX_MODEL_LEN=131072 \
CHAT_MAX_NUM_SEQS=1 \
CHAT_GPU_MEMORY_UTILIZATION=0.95 \
  bash "${START_SERVICES_SCRIPT}" >"${GATE_ROOT}/controller.log" 2>&1
services_started=1

for replicate in 1 2 3; do
  mkdir -p "${GATE_ROOT}/semantic-digests/replicate-${replicate}"
  for baseline in MMFU_Single SimpleMem M2A ViLoMem; do
    slug=$(printf '%s' "${baseline}" | tr '[:upper:]' '[:lower:]')
    UNIT_ROOT="${GATE_ROOT}/replicate-${replicate}/${slug}" \
    BASELINE="${baseline}" \
    SAMPLE_INDEX=100 \
    SAMPLE_ID_EXPECTED=mobile_05 \
    SESSION_COUNT_EXPECTED=11 \
    QA_COUNT_EXPECTED=13 \
    WMA_REPO="${WMA_REPO}" \
    WMA_ENV="${WMA_ENV}" \
    WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
    WMA_DATASET_MANIFEST_SHA256="${WMA_DATASET_MANIFEST_SHA256}" \
    WMA_CONFIG_SHA256="${WMA_CONFIG_SHA256}" \
    SIMPLEMEM_OVERLAY="${SIMPLEMEM_OVERLAY}" \
    VILOMEM_OVERLAY="${VILOMEM_OVERLAY}" \
      bash "${UNIT_SCRIPT}" >>"${GATE_ROOT}/controller.log" 2>&1
    "${WMA_ENV}/bin/python" "${HASH_SCRIPT}" \
      "${GATE_ROOT}/replicate-${replicate}/${slug}" \
      --output "${GATE_ROOT}/semantic-digests/replicate-${replicate}/${slug}.json" \
      >>"${GATE_ROOT}/controller.log" 2>&1
  done
done

"${WMA_ENV}/bin/python" "${AUDIT_SCRIPT}" "${GATE_ROOT}" "${GATE_ROOT}/determinism-audit.json" \
  >>"${GATE_ROOT}/controller.log" 2>&1
SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
CHAT_SESSION="${CHAT_SESSION}" \
EMBED1024_SESSION="${EMBED1024_SESSION}" \
EMBED384_SESSION="${EMBED384_SESSION}" \
  bash "${STOP_SERVICES_SCRIPT}" >>"${GATE_ROOT}/controller.log" 2>&1
services_started=0

printf 'finished_at=%s\n' "$(date -Is)" >>"${GATE_ROOT}/evidence/controller-timing.txt"
find "${GATE_ROOT}" -type f ! -name GATE_SHA256SUMS ! -name TERMINAL_ACCEPTED ! -name TERMINAL_REJECTED -print0 \
  | sort -z | xargs -0 sha256sum >"${GATE_ROOT}/GATE_SHA256SUMS"
touch "${GATE_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
printf 'TERMINAL_ACCEPTED determinism gate\n'
