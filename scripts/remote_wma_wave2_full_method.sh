#!/usr/bin/env bash
set -euo pipefail

: "${RUN_ROOT:?set RUN_ROOT to a fresh project-owned scheduler root}"
: "${BASELINE:?set BASELINE}"
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
: "${RUNTIME_GUARD:?set RUNTIME_GUARD}"
: "${RUNTIME_GUARD_SHA256:?set RUNTIME_GUARD_SHA256}"
: "${WAVE2_SEEDED_LAUNCHER:?set WAVE2_SEEDED_LAUNCHER}"
: "${WAVE2_SEEDED_LAUNCHER_SHA256:?set WAVE2_SEEDED_LAUNCHER_SHA256}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${SHARED_EMBED_MODEL_PATH:?set SHARED_EMBED_MODEL_PATH}"
: "${LIFECYCLE_ROOT:?set LIFECYCLE_ROOT to the accepted method lifecycle root}"
: "${NUMERICAL_AUTHORIZATION:?set NUMERICAL_AUTHORIZATION to the frozen post-lifecycle contract}"
: "${NUMERICAL_AUTHORIZATION_SHA256:?set NUMERICAL_AUTHORIZATION_SHA256}"

WMA_DATASET_MANIFEST_SHA256=9f63a71631ddb2ba506ba4927e4a69e31b8c857a6b72fbd70153201673c8a2cb
WMA_CONFIG_SHA256=74cc054fd3a262571d67deb61f929bca68610b67320f8ea13c6b922e0257a184
SERVICE_ROOT="${RUN_ROOT}/services"
CHAT_SESSION="agentenhance-wma-wave2-chat-${SESSION_SUFFIX}"
PRIMARY_EMBED_SESSION="agentenhance-wma-wave2-primary-${SESSION_SUFFIX}"
AUX_EMBED_SESSION="agentenhance-wma-wave2-aux-${SESSION_SUFFIX}"

case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected scheduler root" >&2; exit 2 ;;
esac
case "${LIFECYCLE_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected lifecycle root" >&2; exit 2 ;;
esac
case "${NUMERICAL_AUTHORIZATION}" in
  /data1/*/AgentEnhance/incoming/*/inputs/comparisons/*.json|/data2/*/AgentEnhance/incoming/*/inputs/comparisons/*.json) ;;
  *) echo "refusing unexpected numerical authorization path" >&2; exit 2 ;;
esac
[[ "${SESSION_SUFFIX}" =~ ^[a-z0-9-]+$ ]] || { echo "unsafe session suffix" >&2; exit 2; }
[[ "${UNIT_SEED}" =~ ^[0-9]+$ ]] || { echo "invalid unit seed" >&2; exit 2; }
[[ ! -e "${RUN_ROOT}" ]] || { echo "refusing existing scheduler root" >&2; exit 3; }

for script_spec in \
  "${START_SERVICES_SCRIPT}:${START_SERVICES_SCRIPT_SHA256}:start-services" \
  "${STOP_SERVICES_SCRIPT}:${STOP_SERVICES_SCRIPT_SHA256}:stop-services" \
  "${UNIT_SCRIPT}:${UNIT_SCRIPT_SHA256}:unit-runner" \
  "${RUNTIME_GUARD}:${RUNTIME_GUARD_SHA256}:runtime-guard" \
  "${WAVE2_SEEDED_LAUNCHER}:${WAVE2_SEEDED_LAUNCHER_SHA256}:seeded-launcher"; do
  script_path=${script_spec%%:*}
  remainder=${script_spec#*:}
  expected_sha256=${remainder%%:*}
  script_label=${remainder#*:}
  [[ -f "${script_path}" ]] || { echo "missing ${script_label}" >&2; exit 3; }
  [[ "$(sha256sum "${script_path}" | awk '{print $1}')" == "${expected_sha256}" ]] || {
    echo "${script_label} digest mismatch" >&2; exit 3;
  }
done
[[ "$(sha256sum "${UNIT_INVENTORY}" | awk '{print $1}')" == "${UNIT_INVENTORY_SHA256}" ]] || { echo "unit inventory digest mismatch" >&2; exit 3; }
[[ "$(sha256sum "${NUMERICAL_AUTHORIZATION}" | awk '{print $1}')" == "${NUMERICAL_AUTHORIZATION_SHA256}" ]] || { echo "numerical authorization digest mismatch" >&2; exit 3; }

profile_json=$("${WMA_ENV}/bin/python" "${RUNTIME_GUARD}" describe --baseline "${BASELINE}")
service_profile=$(printf '%s' "${profile_json}" | jq -r .service_profile)
method_slug=$(printf '%s' "${profile_json}" | jq -r .slug)
test -f "${LIFECYCLE_ROOT}/TERMINAL_ACCEPTED"
test ! -e "${LIFECYCLE_ROOT}/TERMINAL_REJECTED"
test -f "${LIFECYCLE_ROOT}/SHA256SUMS"
sha256sum -c "${LIFECYCLE_ROOT}/SHA256SUMS"
"${WMA_ENV}/bin/python" - "${LIFECYCLE_ROOT}/lifecycle.log" "${NUMERICAL_AUTHORIZATION}" \
  "${BASELINE}" "${START_SERVICES_SCRIPT_SHA256}" "${STOP_SERVICES_SCRIPT_SHA256}" \
  "${UNIT_SCRIPT_SHA256}" "${RUNTIME_GUARD_SHA256}" "${WAVE2_SEEDED_LAUNCHER_SHA256}" <<'PY'
import json
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
prefix = "AGENTENHANCE_WAVE2_ADAPTER_CHECK="
rows = [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
if len(rows) != 1 or rows[0].get("status") != "LIFECYCLE_PASSED" or rows[0].get("baseline") != sys.argv[3]:
    raise SystemExit("lifecycle evidence is not accepted for this baseline")
auth = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if auth.get("status") != "FROZEN_BEFORE_EXECUTION" or sys.argv[3] not in auth.get("methods", []):
    raise SystemExit("numerical authorization does not admit this baseline")
observed = auth.get("implementation", {})
expected = {
    "start_services_sha256": sys.argv[4],
    "stop_services_sha256": sys.argv[5],
    "unit_runner_sha256": sys.argv[6],
    "runtime_guard_sha256": sys.argv[7],
    "seeded_launcher_sha256": sys.argv[8],
}
if any(observed.get(key) != value for key, value in expected.items()):
    raise SystemExit("numerical authorization implementation hash mismatch")
PY

mkdir -p "${RUN_ROOT}/units" "${RUN_ROOT}/evidence"
services_started=0
gpu_monitor_pid=
stop_gpu_monitor() {
  if [[ -n "${gpu_monitor_pid}" ]]; then
    kill "${gpu_monitor_pid}" 2>/dev/null || true
    wait "${gpu_monitor_pid}" 2>/dev/null || true
    gpu_monitor_pid=
  fi
}
scheduler_terminalize() {
  local code=$?
  stop_gpu_monitor
  if (( services_started == 1 )); then
    SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
    CHAT_SESSION="${CHAT_SESSION}" \
    PRIMARY_EMBED_SESSION="${PRIMARY_EMBED_SESSION}" \
    AUX_EMBED_SESSION="${AUX_EMBED_SESSION}" \
      bash "${STOP_SERVICES_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1 || true
  fi
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${RUN_ROOT}/SCHEDULER_TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap scheduler_terminalize EXIT

printf 'baseline=%s\nmethod_slug=%s\nservice_profile=%s\nseed=%s\nstarted_at=%s\nunit_inventory_sha256=%s\nlifecycle_inventory_sha256=%s\nnumerical_authorization_sha256=%s\n' \
  "${BASELINE}" "${method_slug}" "${service_profile}" "${UNIT_SEED}" "$(date -Is)" \
  "${UNIT_INVENTORY_SHA256}" "$(sha256sum "${LIFECYCLE_ROOT}/SHA256SUMS" | awk '{print $1}')" \
  "${NUMERICAL_AUTHORIZATION_SHA256}" >"${RUN_ROOT}/evidence/scheduler-identity.txt"
printf 'sample_index,sample_id,unit_root,reason\n' >"${RUN_ROOT}/rejected-units.csv"

SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
SERVICE_PROFILE="${service_profile}" \
CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
SHARED_EMBED_MODEL_PATH="${SHARED_EMBED_MODEL_PATH}" \
WAVE2_GME_MODEL_PATH="${WAVE2_GME_MODEL_PATH:-}" \
WAVE2_GME_MATERIALIZATION_ROOT="${WAVE2_GME_MATERIALIZATION_ROOT:-}" \
WAVE2_QWEN_MODEL_PATH="${WAVE2_QWEN_MODEL_PATH:-}" \
WAVE2_QWEN_MATERIALIZATION_ROOT="${WAVE2_QWEN_MATERIALIZATION_ROOT:-}" \
CHAT_SESSION="${CHAT_SESSION}" \
PRIMARY_EMBED_SESSION="${PRIMARY_EMBED_SESSION}" \
AUX_EMBED_SESSION="${AUX_EMBED_SESSION}" \
  bash "${START_SERVICES_SCRIPT}" >"${RUN_ROOT}/scheduler.log" 2>&1
services_started=1

printf 'timestamp_unix,timestamp_iso,gpu_index,memory_used_mib,memory_total_mib,utilization_gpu_percent\n' >"${RUN_ROOT}/evidence/gpu-monitor.csv"
(
  while true; do
    timestamp_unix=$(date +%s)
    timestamp_iso=$(date -Is)
    nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits \
      | awk -F',' -v ts="${timestamp_unix}" -v iso="${timestamp_iso}" '
          BEGIN { OFS="," }
          {
            for (i = 1; i <= NF; i++) gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
            if ($1 == 1 || $1 == 3 || $1 == 4 || $1 == 5) print ts, iso, $1, $2, $3, $4
          }'
    sleep 5
  done
) >>"${RUN_ROOT}/evidence/gpu-monitor.csv" 2>>"${RUN_ROOT}/scheduler.log" &
gpu_monitor_pid=$!

accepted=0
rejected=0
infrastructure_failure=0
while IFS=, read -r sample_index sample_id relative_json_path sessions turns attachments qa source_json_sha256; do
  [[ "${sample_index}" == sample_index ]] && continue
  unit_root=$(printf '%s/units/%03d_%s' "${RUN_ROOT}" "${sample_index}" "${sample_id}")
  if UNIT_ROOT="${unit_root}" \
    BASELINE="${BASELINE}" \
    SAMPLE_INDEX="${sample_index}" \
    SAMPLE_ID_EXPECTED="${sample_id}" \
    SESSION_COUNT_EXPECTED="${sessions}" \
    QA_COUNT_EXPECTED="${qa}" \
    ATTACHMENT_COUNT_EXPECTED="${attachments}" \
    UNIT_SEED="${UNIT_SEED}" \
    SERVICE_ROOT="${SERVICE_ROOT}" \
    WMA_REPO="${WMA_REPO}" \
    WMA_ENV="${WMA_ENV}" \
    WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
    WMA_DATASET_MANIFEST_SHA256="${WMA_DATASET_MANIFEST_SHA256}" \
    WMA_CONFIG_SHA256="${WMA_CONFIG_SHA256}" \
    SIMPLEMEM_OVERLAY="${SIMPLEMEM_OVERLAY:-}" \
    RUNTIME_GUARD="${RUNTIME_GUARD}" \
    RUNTIME_GUARD_SHA256="${RUNTIME_GUARD_SHA256}" \
    WAVE2_SEEDED_LAUNCHER="${WAVE2_SEEDED_LAUNCHER}" \
    WAVE2_SEEDED_LAUNCHER_SHA256="${WAVE2_SEEDED_LAUNCHER_SHA256}" \
      bash "${UNIT_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1; then
    accepted=$((accepted + 1))
  else
    rejected=$((rejected + 1))
    printf '%s,%s,%s,unit_nonzero_exit\n' "${sample_index}" "${sample_id}" "${unit_root}" >>"${RUN_ROOT}/rejected-units.csv"
    if ! curl -fsS http://127.0.0.1:18220/v1/models >/dev/null \
      || ! curl -fsS http://127.0.0.1:18221/v1/models >/dev/null \
      || ! curl -fsS http://127.0.0.1:18222/v1/models >/dev/null; then
      infrastructure_failure=1
      break
    fi
  fi
  printf 'accepted=%s\nrejected=%s\nlast_sample_index=%s\nlast_sample_id=%s\nupdated_at=%s\n' \
    "${accepted}" "${rejected}" "${sample_index}" "${sample_id}" "$(date -Is)" >"${RUN_ROOT}/progress.txt"
  if ! kill -0 "${gpu_monitor_pid}" 2>/dev/null; then
    infrastructure_failure=1
    printf 'gpu monitor terminated before scheduler completion\n' >>"${RUN_ROOT}/scheduler.log"
    break
  fi
done <"${UNIT_INVENTORY}"

stop_gpu_monitor
SERVICE_RUN_ROOT="${SERVICE_ROOT}" \
CHAT_SESSION="${CHAT_SESSION}" \
PRIMARY_EMBED_SESSION="${PRIMARY_EMBED_SESSION}" \
AUX_EMBED_SESSION="${AUX_EMBED_SESSION}" \
  bash "${STOP_SERVICES_SCRIPT}" >>"${RUN_ROOT}/scheduler.log" 2>&1
services_started=0

printf 'accepted=%s\nrejected=%s\ninfrastructure_failure=%s\nfinished_at=%s\n' \
  "${accepted}" "${rejected}" "${infrastructure_failure}" "$(date -Is)" >"${RUN_ROOT}/scheduler-summary.txt"
find "${RUN_ROOT}" -type f ! -name SCHEDULER_SHA256SUMS ! -name 'SCHEDULER_*' -print0 \
  | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SCHEDULER_SHA256SUMS"
if (( accepted == 150 && rejected == 0 && infrastructure_failure == 0 )); then
  touch "${RUN_ROOT}/SCHEDULER_EXECUTION_ACCEPTED"
  scheduler_exit_code=0
else
  touch "${RUN_ROOT}/SCHEDULER_EXECUTION_WITH_REJECTIONS"
  scheduler_exit_code=5
fi
trap - EXIT
printf 'scheduler finished baseline=%s seed=%s accepted=%s rejected=%s infrastructure_failure=%s\n' \
  "${BASELINE}" "${UNIT_SEED}" "${accepted}" "${rejected}" "${infrastructure_failure}"
exit "${scheduler_exit_code}"
