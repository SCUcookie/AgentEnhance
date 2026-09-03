#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${RUN_ROOT:?set RUN_ROOT to a fresh project-owned run directory}"
: "${BASELINE:?set BASELINE}"
: "${CHECK_SCRIPT:?set CHECK_SCRIPT}"
: "${CHECK_SCRIPT_SHA256:?set CHECK_SCRIPT_SHA256}"
: "${GUARDED_LAUNCHER:?set GUARDED_LAUNCHER}"
: "${GUARDED_LAUNCHER_SHA256:?set GUARDED_LAUNCHER_SHA256}"
: "${RUNTIME_GUARD:?set RUNTIME_GUARD}"
: "${RUNTIME_GUARD_SHA256:?set RUNTIME_GUARD_SHA256}"
: "${IMAGE_PATH:?set IMAGE_PATH}"
: "${IMAGE_SHA256:?set IMAGE_SHA256}"
: "${SERVICE_ROOT:?set SERVICE_ROOT}"

CHAT_BASE_URL=http://127.0.0.1:18220/v1
PRIMARY_EMBED_BASE_URL=http://127.0.0.1:18221/v1

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected run root" >&2; exit 2 ;;
esac
case "${SERVICE_ROOT}" in
  /data1/*/AgentEnhance/runs/*/services|/data2/*/AgentEnhance/runs/*/services) ;;
  *) echo "refusing unexpected service root" >&2; exit 2 ;;
esac
[[ ! -e "${RUN_ROOT}" ]] || { echo "refusing existing run root" >&2; exit 3; }
for path_hash in \
  "${CHECK_SCRIPT}:${CHECK_SCRIPT_SHA256}:checker" \
  "${GUARDED_LAUNCHER}:${GUARDED_LAUNCHER_SHA256}:guarded-launcher" \
  "${RUNTIME_GUARD}:${RUNTIME_GUARD_SHA256}:runtime-guard"; do
  path=${path_hash%%:*}
  rest=${path_hash#*:}
  expected=${rest%%:*}
  label=${rest#*:}
  test -f "${path}" || { echo "missing ${label}" >&2; exit 3; }
  [[ "$(sha256sum "${path}" | awk '{print $1}')" == "${expected}" ]] || { echo "${label} digest mismatch" >&2; exit 3; }
done
[[ "$(sha256sum "${IMAGE_PATH}" | awk '{print $1}')" == "${IMAGE_SHA256}" ]] || { echo "image digest mismatch" >&2; exit 3; }
[[ "$(git -C "${WMA_REPO}" rev-parse HEAD)" == 15ea25b723d9c4fb35e8062037aec6a5601e4442 ]] || { echo "source commit mismatch" >&2; exit 3; }
[[ -z "$(git -C "${WMA_REPO}" status --porcelain)" ]] || { echo "source checkout is dirty" >&2; exit 3; }
test -f "${SERVICE_ROOT}/SERVICE_READY"
test -f "${SERVICE_ROOT}/evidence/service-contract.json"

profile_json=$("${WMA_ENV}/bin/python" "${RUNTIME_GUARD}" describe --baseline "${BASELINE}")
service_profile=$(printf '%s' "${profile_json}" | jq -r .service_profile)
primary_model=$(printf '%s' "${profile_json}" | jq -r .primary_embedding_model)
primary_dim=$(printf '%s' "${profile_json}" | jq -r .primary_embedding_dim)
"${WMA_ENV}/bin/python" - "${SERVICE_ROOT}/evidence/service-contract.json" \
  "${service_profile}" "${primary_model}" "${primary_dim}" <<'PY'
import json
import sys
from pathlib import Path

contract = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
primary = contract.get("primary_embedding", {})
if contract.get("status") != "SERVICE_READY" or contract.get("service_profile") != sys.argv[2]:
    raise SystemExit("lifecycle service profile mismatch")
if primary.get("model") != sys.argv[3] or primary.get("dimension") != int(sys.argv[4]):
    raise SystemExit("lifecycle embedding identity mismatch")
PY

mkdir -p "${RUN_ROOT}/evidence" "${RUN_ROOT}/baseline-storage/tmp"
seal_failed_root() {
  local status=$?
  if (( status != 0 )) && [[ ! -e "${RUN_ROOT}/TERMINAL_ACCEPTED" && ! -e "${RUN_ROOT}/TERMINAL_REJECTED" ]]; then
    printf '%s\n' "${status}" >"${RUN_ROOT}/failure-exit-code.txt"
    find "${RUN_ROOT}" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SHA256SUMS"
    touch "${RUN_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${status}"
}
trap seal_failed_root EXIT

chat_log=${SERVICE_ROOT}/logs/chat.log
primary_log=${SERVICE_ROOT}/logs/primary-embedding.log
chat_offset=$(stat -c%s "${chat_log}")
primary_offset=$(stat -c%s "${primary_log}")
python_path="$(dirname "${RUNTIME_GUARD}"):${WMA_REPO}"
if [[ "${BASELINE}" == Omni-SimpleMem ]]; then
  : "${SIMPLEMEM_OVERLAY:?Omni-SimpleMem requires the frozen SimpleMem overlay}"
  simplemem_source="${WMA_REPO}/eval_framework/baselines/SimpleMem"
  python_path="$(dirname "${RUNTIME_GUARD}"):${SIMPLEMEM_OVERLAY}:${simplemem_source}:${WMA_REPO}"
fi
extra_env=()
if [[ "${service_profile}" == gme1536 ]]; then
  extra_env+=(GME_BASE_URL="${PRIMARY_EMBED_BASE_URL}" GME_MODEL="${primary_model}" GME_API_KEY=EMPTY)
fi
if [[ "${service_profile}" == qwen4096 ]]; then
  extra_env+=(
    QWEN_VL_EMBED_BASE_URL="${PRIMARY_EMBED_BASE_URL}"
    QWEN_VL_EMBED_MODEL="${primary_model}"
    QWEN_VL_EMBED_API_KEY=EMPTY
    QWEN_VL_EMBED_REMOTE_IMAGES=1
  )
fi

started_at=$(date -Is)
set +e
env \
  "${extra_env[@]}" \
  PYTHONPATH="${python_path}" \
  AGENTENHANCE_WMA_REPO="${WMA_REPO}" \
  OPENAI_API_KEY=EMPTY \
  OPENAI_MODEL=Qwen3-VL-8B-Instruct \
  OPENAI_BASE_URL="${CHAT_BASE_URL}" \
  OPENAI_TEMPERATURE=0 \
  OPENAI_EMBEDDING_MODEL="${primary_model}" \
  OPENAI_EMBEDDING_BASE_URL="${PRIMARY_EMBED_BASE_URL}" \
  LOCAL_EMBEDDING_DIMS="${primary_dim}" \
  TMPDIR="${RUN_ROOT}/baseline-storage/tmp" \
  SIMPLEMEM_LANCEDB_PATH="${RUN_ROOT}/baseline-storage/lancedb" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "${WMA_ENV}/bin/python" "${GUARDED_LAUNCHER}" \
    --baseline "${BASELINE}" \
    --checker "${CHECK_SCRIPT}" \
    --repo-root "${WMA_REPO}" \
    --image-path "${IMAGE_PATH}" \
    --image-sha256 "${IMAGE_SHA256}" \
  >"${RUN_ROOT}/lifecycle.log" 2>"${RUN_ROOT}/lifecycle.stderr"
checker_status=$?
set -e

capture_log_delta() {
  local source=$1 offset=$2 destination=$3 size
  size=$(stat -c%s "${source}")
  (( size >= offset )) || { echo "service log shrank during lifecycle" >&2; return 1; }
  tail -c "+$((offset + 1))" "${source}" >"${destination}"
}
capture_log_delta "${chat_log}" "${chat_offset}" "${RUN_ROOT}/evidence/chat-service.log"
capture_log_delta "${primary_log}" "${primary_offset}" "${RUN_ROOT}/evidence/primary-embedding-service.log"
finished_at=$(date -Is)
printf 'baseline\tservice_profile\tstarted_at\tfinished_at\tsource_commit\tembed_dim\tchecker_exit\n%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "${BASELINE}" "${service_profile}" "${started_at}" "${finished_at}" \
  15ea25b723d9c4fb35e8062037aec6a5601e4442 "${primary_dim}" "${checker_status}" >"${RUN_ROOT}/timing.tsv"

(( checker_status == 0 )) || { echo "lifecycle checker failed" >&2; exit 5; }
grep -q '"status": "LIFECYCLE_PASSED"' "${RUN_ROOT}/lifecycle.log"
grep -q 'AGENTENHANCE_WAVE2_RUNTIME_GUARD=' "${RUN_ROOT}/lifecycle.log"
if [[ "${BASELINE}" == MIRIX ]]; then
  grep -q 'AGENTENHANCE_MIRIX_ENDPOINT_GUARD_ACTIVE=' "${RUN_ROOT}/lifecycle.log"
fi
if [[ "${BASELINE}" == Qwen3-VL-Embedding-8B ]]; then
  grep -q '"qwen_remote_images": "1"' "${RUN_ROOT}/lifecycle.log"
fi
! grep -Eq 'Traceback \(most recent call last\)|CUDA out of memory|Error analyzing content:|\[Omni-SimpleMem\] add_text failed|\[Omni-SimpleMem\] add_image\(.+\) failed' "${RUN_ROOT}/lifecycle.log" "${RUN_ROOT}/lifecycle.stderr"
for log in "${RUN_ROOT}/evidence/chat-service.log" "${RUN_ROOT}/evidence/primary-embedding-service.log"; do
  ! grep -Eq 'HTTP/[0-9.]+" [45][0-9][0-9]|CUDA out of memory|Traceback \(most recent call last\)' "${log}"
done

find "${RUN_ROOT}" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >"${RUN_ROOT}/SHA256SUMS"
touch "${RUN_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
tail -n 1 "${RUN_ROOT}/lifecycle.log"
