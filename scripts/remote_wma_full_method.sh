#!/usr/bin/env bash
set -euo pipefail

: "${RUN_ROOT:?set RUN_ROOT to a fresh project-owned scheduler root}"
: "${BASELINE:?set BASELINE}"
: "${METHOD_SLUG:?set METHOD_SLUG}"
: "${UNIT_SEED:?set UNIT_SEED}"
: "${SESSION_SUFFIX:?set SESSION_SUFFIX}"
: "${UNIT_INVENTORY:?set UNIT_INVENTORY}"
: "${UNIT_INVENTORY_SHA256:?set UNIT_INVENTORY_SHA256}"
: "${START_SERVICES_SCRIPT:?set START_SERVICES_SCRIPT}"
: "${START_SERVICES_SCRIPT_SHA256:?set START_SERVICES_SCRIPT_SHA256}"
: "${STOP_SERVICES_SCRIPT:?set STOP_SERVICES_SCRIPT}"
: "${STOP_SERVICES_SCRIPT_SHA256:?set STOP_SERVICES_SCRIPT_SHA256}"
: "${UNIT_SCRIPT:?set UNIT_SCRIPT}"
: "${UNIT_SCRIPT_SHA256:?set UNIT_SCRIPT_SHA256}"
: "${WMA_SEEDED_LAUNCHER:?set WMA_SEEDED_LAUNCHER}"
: "${WMA_SEEDED_LAUNCHER_SHA256:?set WMA_SEEDED_LAUNCHER_SHA256}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${SIMPLEMEM_OVERLAY:?set SIMPLEMEM_OVERLAY}"
: "${VILOMEM_OVERLAY:?set VILOMEM_OVERLAY}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

WMA_DATASET_MANIFEST_SHA256=9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb
WMA_CONFIG_SHA256=74cc054fd3a262571d67deb61f929bca68610b67320f8ea13c6b922e0257a184
SERVICE_ROOT="${RUN_ROOT}/services"
CHAT_SESSION="agentenhance-wma-chat-${SESSION_SUFFIX}"
EMBED1024_SESSION="agentenhance-wma-e1024-${SESSION_SUFFIX}"
EMBED384_SESSION="agentenhance-wma-e384-${SESSION_SUFFIX}"

case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected scheduler root" >&2; exit 2 ;;
esac
case "${BASELINE}:${METHOD_SLUG}" in
  MMFU_Single:mmfu_single|SimpleMem:simplemem|M2A:m2a|ViLoMem:vilomem) ;;
  *) echo "baseline/method slug mismatch" >&2; exit 2 ;;
esac
[[ "${SESSION_SUFFIX}" =~ ^[a-z0-9-]+$ ]] || { echo "unsafe session suffix" >&2; exit 2; }
[[ "${UNIT_SEED}" =~ ^[0-9]+$ ]] || { echo "invalid unit seed" >&2; exit 2; }
[[ ! -e "${RUN_ROOT}" ]] || { echo "refusing existing scheduler root" >&2; exit 3; }
[[ "$(sha256sum "${UNIT_INVENTORY}" | awk '{print $1}')" == "${UNIT_INVENTORY_SHA256}" ]] || {
  echo "unit inventory digest mismatch" >&2; exit 3;
}
for script_spec in \
  "${START_SERVICES_SCRIPT}:${START_SERVICES_SCRIPT_SHA256}:start-services" \
  "${STOP_SERVICES_SCRIPT}:${STOP_SERVICES_SCRIPT_SHA256}:stop-services" \
  "${UNIT_SCRIPT}:${UNIT_SCRIPT_SHA256}:unit-runner"; do
  script_path=${script_spec%%:*}
  remainder=${script_spec#*:}
  expected_sha256=${remainder%%:*}
  script_label=${remainder#*:}
  [[ -f "${script_path}" ]] || { echo "missing ${script_label} script" >&2; exit 3; }
  [[ "$(sha256sum "${script_path}" | awk '{print $1}')" == "${expected_sha256}" ]] || {
    echo "${script_label} script digest mismatch" >&2; exit 3;
  }
done

mkdir -p "${RUN_ROOT}/units" "${RUN_ROOT}/evidence"
services_started=0
scheduler_terminalize() {
  local code=$?
  if (( services_started == 1 )); then
    SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
    CHAT_SESSION="${CHAT_SESSION}" \
    EMBED1024_SESSION="${EMBED1024_SESSION}" \
    EMBED384_SESSION="${EMBED384_SESSION}" \
      bash "${STOP_SERVICES_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1 || true
  fi
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${RUN_ROOT}/SCHEDULER_TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap scheduler_terminalize EXIT

printf 'baseline=%s\nseed=%s\nstarted_at=%s\nunit_inventory_sha256=%s\nstart_services_sha256=%s\nstop_services_sha256=%s\nunit_runner_sha256=%s\nseeded_launcher_sha256=%s\n' \
  "${BASELINE}" "${UNIT_SEED}" "$(date -Is)" "${UNIT_INVENTORY_SHA256}" \
  "${START_SERVICES_SCRIPT_SHA256}" "${STOP_SERVICES_SCRIPT_SHA256}" \
  "${UNIT_SCRIPT_SHA256}" "${WMA_SEEDED_LAUNCHER_SHA256}" \
  >"${RUN_ROOT}/evidence/scheduler-identity.txt"
printf 'sample_index,sample_id,unit_root,reason\n' >"${RUN_ROOT}/rejected-units.csv"

SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
EMBED_MODEL_PATH="${EMBED_MODEL_PATH}" \
CHAT_SESSION="${CHAT_SESSION}" \
EMBED1024_SESSION="${EMBED1024_SESSION}" \
EMBED384_SESSION="${EMBED384_SESSION}" \
CHAT_MAX_MODEL_LEN=131072 \
CHAT_MAX_NUM_SEQS=1 \
CHAT_GPU_MEMORY_UTILIZATION=0.95 \
  bash "${START_SERVICES_SCRIPT}" >"${RUN_ROOT}/scheduler.log" 2>&1
services_started=1

accepted=0
rejected=0
infrastructure_failure=0
while IFS=, read -r sample_index sample_id relative_json_path sessions turns attachments qa source_json_sha256; do
  [[ "${sample_index}" == "sample_index" ]] && continue
  unit_root=$(printf '%s/units/%03d_%s' "${RUN_ROOT}" "${sample_index}" "${sample_id}")
  if UNIT_ROOT="${unit_root}" \
    BASELINE="${BASELINE}" \
    SAMPLE_INDEX="${sample_index}" \
    SAMPLE_ID_EXPECTED="${sample_id}" \
    SESSION_COUNT_EXPECTED="${sessions}" \
    QA_COUNT_EXPECTED="${qa}" \
    UNIT_SEED="${UNIT_SEED}" \
    WMA_REPO="${WMA_REPO}" \
    WMA_ENV="${WMA_ENV}" \
    WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
    WMA_DATASET_MANIFEST_SHA256="${WMA_DATASET_MANIFEST_SHA256}" \
    WMA_CONFIG_SHA256="${WMA_CONFIG_SHA256}" \
    SIMPLEMEM_OVERLAY="${SIMPLEMEM_OVERLAY}" \
    VILOMEM_OVERLAY="${VILOMEM_OVERLAY}" \
    WMA_SEEDED_LAUNCHER="${WMA_SEEDED_LAUNCHER}" \
    WMA_SEEDED_LAUNCHER_SHA256="${WMA_SEEDED_LAUNCHER_SHA256}" \
      bash "${UNIT_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1; then
    accepted=$((accepted + 1))
  else
    rejected=$((rejected + 1))
    printf '%s,%s,%s,unit_nonzero_exit\n' "${sample_index}" "${sample_id}" "${unit_root}" \
      >>"${RUN_ROOT}/rejected-units.csv"
    if ! curl -fsS http://127.0.0.1:18120/v1/models >/dev/null \
      || ! curl -fsS http://127.0.0.1:18113/v1/models >/dev/null \
      || ! curl -fsS http://127.0.0.1:18114/v1/models >/dev/null; then
      infrastructure_failure=1
      break
    fi
  fi
  printf 'accepted=%s\nrejected=%s\nlast_sample_index=%s\nlast_sample_id=%s\nupdated_at=%s\n' \
    "${accepted}" "${rejected}" "${sample_index}" "${sample_id}" "$(date -Is)" \
    >"${RUN_ROOT}/progress.txt"
done <"${UNIT_INVENTORY}"

SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
CHAT_SESSION="${CHAT_SESSION}" \
EMBED1024_SESSION="${EMBED1024_SESSION}" \
EMBED384_SESSION="${EMBED384_SESSION}" \
  bash "${STOP_SERVICES_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1
services_started=0

printf 'accepted=%s\nrejected=%s\ninfrastructure_failure=%s\nfinished_at=%s\n' \
  "${accepted}" "${rejected}" "${infrastructure_failure}" "$(date -Is)" \
  >"${RUN_ROOT}/scheduler-summary.txt"
find "${RUN_ROOT}" -type f ! -name SCHEDULER_SHA256SUMS ! -name 'SCHEDULER_*' -print0 \
  | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SCHEDULER_SHA256SUMS"
if (( accepted == 150 && rejected == 0 && infrastructure_failure == 0 )); then
  touch "${RUN_ROOT}/SCHEDULER_EXECUTION_ACCEPTED"
else
  touch "${RUN_ROOT}/SCHEDULER_EXECUTION_WITH_REJECTIONS"
fi
trap - EXIT
printf 'scheduler finished baseline=%s seed=%s accepted=%s rejected=%s infrastructure_failure=%s\n' \
  "${BASELINE}" "${UNIT_SEED}" "${accepted}" "${rejected}" "${infrastructure_failure}"
