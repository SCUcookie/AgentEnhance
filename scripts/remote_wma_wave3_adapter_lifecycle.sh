#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO to the frozen WorldMemArena checkout}"
: "${WMA_COMMIT:?set WMA_COMMIT to the frozen WorldMemArena commit}"
: "${METHOD_ENV:?set METHOD_ENV to the accepted isolated Python environment}"
: "${RUN_ROOT:?set RUN_ROOT to a fresh project-owned run root}"
: "${BASELINE:?set BASELINE to MemoryOS or MemGAS}"
: "${CHECK_SCRIPT:?set CHECK_SCRIPT}"
: "${CHECK_SCRIPT_SHA256:?set CHECK_SCRIPT_SHA256}"
: "${OVERLAY_ROOT:?set OVERLAY_ROOT}"
: "${SITECUSTOMIZE_SHA256:?set SITECUSTOMIZE_SHA256}"
: "${ADAPTER_SHA256:?set ADAPTER_SHA256}"
: "${SOURCE_ROOT:?set SOURCE_ROOT to the accepted source-only import root}"
: "${EXECUTION_SOURCE_RECORD:?set EXECUTION_SOURCE_RECORD}"
: "${EXECUTION_SOURCE_RECORD_SHA256:?set EXECUTION_SOURCE_RECORD_SHA256}"
: "${MODEL_ROOT:?set MODEL_ROOT to the accepted immutable embedding snapshot}"
: "${MODEL_SHA256SUMS:?set MODEL_SHA256SUMS}"
: "${MODEL_RECORD:?set MODEL_RECORD to the accepted model-materialization record}"
: "${MODEL_RECORD_SHA256:?set MODEL_RECORD_SHA256}"
: "${ENVIRONMENT_RECORD:?set ENVIRONMENT_RECORD}"
: "${ENVIRONMENT_RECORD_SHA256:?set ENVIRONMENT_RECORD_SHA256}"
: "${IMAGE_PATH:?set IMAGE_PATH}"
: "${IMAGE_SHA256:?set IMAGE_SHA256}"
: "${WMA_CHAT_BASE_URL:?set WMA_CHAT_BASE_URL}"

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected lifecycle run root" >&2; exit 2 ;;
esac
case "${METHOD_ENV}" in
  /data1/*/AgentEnhance/environments/*|/data2/*/AgentEnhance/environments/*) ;;
  *) echo "refusing unexpected method environment" >&2; exit 2 ;;
esac
case "${MODEL_ROOT}" in
  /data1/*/AgentEnhance/cache/models/*|/data2/*/AgentEnhance/cache/models/*) ;;
  *) echo "refusing unexpected model root" >&2; exit 2 ;;
esac
case "${BASELINE}" in
  MemoryOS) adapter_file=${OVERLAY_ROOT}/memoryos_wma_adapter.py ;;
  MemGAS) adapter_file=${OVERLAY_ROOT}/memgas_wma_adapter.py ;;
  *) echo "unsupported Wave-3 baseline: ${BASELINE}" >&2; exit 2 ;;
esac

[[ ! -e "${RUN_ROOT}" ]] || { echo "refusing existing lifecycle root" >&2; exit 3; }
[[ -x "${METHOD_ENV}/bin/python" ]] || { echo "missing accepted Python environment" >&2; exit 3; }
[[ -f "${CHECK_SCRIPT}" ]] || { echo "missing lifecycle checker" >&2; exit 3; }
[[ -f "${OVERLAY_ROOT}/sitecustomize.py" && -f "${adapter_file}" ]] || {
  echo "missing adapter overlay" >&2; exit 3;
}
[[ -d "${SOURCE_ROOT}" ]] || { echo "missing execution source" >&2; exit 3; }
[[ -d "${MODEL_ROOT}" ]] || { echo "missing embedding model" >&2; exit 3; }
[[ -f "${IMAGE_PATH}" ]] || { echo "missing fixed lifecycle image" >&2; exit 3; }
[[ "$(git -C "${WMA_REPO}" rev-parse HEAD)" == "${WMA_COMMIT}" ]] || {
  echo "WorldMemArena commit mismatch" >&2; exit 3;
}
[[ -z "$(git -C "${WMA_REPO}" status --porcelain)" ]] || {
  echo "WorldMemArena checkout is dirty" >&2; exit 3;
}

printf '%s  %s\n' "${CHECK_SCRIPT_SHA256}" "${CHECK_SCRIPT}" | sha256sum -c -
printf '%s  %s\n' "${SITECUSTOMIZE_SHA256}" "${OVERLAY_ROOT}/sitecustomize.py" | sha256sum -c -
printf '%s  %s\n' "${ADAPTER_SHA256}" "${adapter_file}" | sha256sum -c -
printf '%s  %s\n' "${EXECUTION_SOURCE_RECORD_SHA256}" "${EXECUTION_SOURCE_RECORD}" | sha256sum -c -
printf '%s  %s\n' "${MODEL_RECORD_SHA256}" "${MODEL_RECORD}" | sha256sum -c -
printf '%s  %s\n' "${ENVIRONMENT_RECORD_SHA256}" "${ENVIRONMENT_RECORD}" | sha256sum -c -
printf '%s  %s\n' "${IMAGE_SHA256}" "${IMAGE_PATH}" | sha256sum -c -
grep -q '"status": "TERMINAL_ACCEPTED"' "${EXECUTION_SOURCE_RECORD}"
grep -q '"status": "TERMINAL_ACCEPTED"' "${MODEL_RECORD}"
grep -q '"status": "TERMINAL_ACCEPTED"' "${ENVIRONMENT_RECORD}"
test "$(find "${SOURCE_ROOT}" -type f -name '*.pyc' | wc -l)" -eq 0
(cd "${MODEL_ROOT}" && sha256sum -c "${MODEL_SHA256SUMS}")
"${METHOD_ENV}/bin/python" -m pip check

mkdir -p "${RUN_ROOT}/evidence"
seal_failed_root() {
  status=$?
  if [[ "${status}" -ne 0 && ! -e "${RUN_ROOT}/TERMINAL_ACCEPTED" && ! -e "${RUN_ROOT}/TERMINAL_REJECTED" ]]; then
    printf '%s\n' "${status}" >"${RUN_ROOT}/failure-exit-code.txt"
    find "${RUN_ROOT}" -type f ! -name SHA256SUMS -print0 \
      | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SHA256SUMS"
    touch "${RUN_ROOT}/TERMINAL_REJECTED"
  fi
}
trap seal_failed_root EXIT

curl -fsS "${WMA_CHAT_BASE_URL}/models" >"${RUN_ROOT}/evidence/chat-models.json"
"${METHOD_ENV}/bin/python" --version >"${RUN_ROOT}/evidence/python-version.txt" 2>&1
"${METHOD_ENV}/bin/python" -m pip freeze --all >"${RUN_ROOT}/evidence/pip-freeze.txt"

started_at=$(date -Is)
set +e
env \
  PYTHONPATH="${OVERLAY_ROOT}:${WMA_REPO}" \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONHASHSEED=0 \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  TOKENIZERS_PARALLELISM=false \
  OMP_NUM_THREADS=2 \
  MKL_NUM_THREADS=2 \
  OPENAI_API_KEY=EMPTY \
  OPENAI_MODEL=Qwen3-VL-8B-Instruct \
  OPENAI_BASE_URL="${WMA_CHAT_BASE_URL}" \
  MEMORYOS_EMBED_DEVICE=cpu \
  MEMGAS_EMBED_DEVICE=cpu \
  /usr/bin/time -v -o "${RUN_ROOT}/resource-usage.txt" \
  "${METHOD_ENV}/bin/python" "${CHECK_SCRIPT}" \
    --baseline "${BASELINE}" \
    --source-root "${SOURCE_ROOT}" \
    --storage-root "${RUN_ROOT}/storage" \
    --embedding-model-path "${MODEL_ROOT}" \
    --image-path "${IMAGE_PATH}" \
    --image-sha256 "${IMAGE_SHA256}" \
  >"${RUN_ROOT}/lifecycle.log" 2>"${RUN_ROOT}/lifecycle.stderr"
checker_status=$?
set -e
finished_at=$(date -Is)

printf 'baseline\tstarted_at\tfinished_at\tchecker_exit\n%s\t%s\t%s\t%s\n' \
  "${BASELINE}" "${started_at}" "${finished_at}" "${checker_status}" \
  >"${RUN_ROOT}/timing.tsv"
if [[ "${checker_status}" -ne 0 ]] || ! grep -q '"status": "LIFECYCLE_PASSED"' "${RUN_ROOT}/lifecycle.log"; then
  find "${RUN_ROOT}" -type f ! -name SHA256SUMS -print0 \
    | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SHA256SUMS"
  touch "${RUN_ROOT}/TERMINAL_REJECTED"
  exit 5
fi

find "${RUN_ROOT}" -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SHA256SUMS"
touch "${RUN_ROOT}/TERMINAL_ACCEPTED"
tail -n 1 "${RUN_ROOT}/lifecycle.log"
