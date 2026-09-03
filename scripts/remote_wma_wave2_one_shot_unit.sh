#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${WMA_DATASET_MANIFEST_SHA256:?set WMA_DATASET_MANIFEST_SHA256}"
: "${WMA_CONFIG_SHA256:?set WMA_CONFIG_SHA256}"
: "${UNIT_ROOT:?set UNIT_ROOT to a fresh project-owned run directory}"
: "${BASELINE:?set BASELINE}"
: "${SAMPLE_INDEX:?set SAMPLE_INDEX}"
: "${SAMPLE_ID_EXPECTED:?set SAMPLE_ID_EXPECTED}"
: "${SESSION_COUNT_EXPECTED:?set SESSION_COUNT_EXPECTED}"
: "${QA_COUNT_EXPECTED:?set QA_COUNT_EXPECTED}"
: "${ATTACHMENT_COUNT_EXPECTED:?set ATTACHMENT_COUNT_EXPECTED}"
: "${UNIT_SEED:?set UNIT_SEED}"
: "${SERVICE_ROOT:?set SERVICE_ROOT}"
: "${RUNTIME_GUARD:?set RUNTIME_GUARD}"
: "${RUNTIME_GUARD_SHA256:?set RUNTIME_GUARD_SHA256}"
: "${WAVE2_SEEDED_LAUNCHER:?set WAVE2_SEEDED_LAUNCHER}"
: "${WAVE2_SEEDED_LAUNCHER_SHA256:?set WAVE2_SEEDED_LAUNCHER_SHA256}"

SOURCE_COMMIT=15ea25b723d9c4fb35e8062037aec6a5601e4442
CHAT_BASE_URL=http://127.0.0.1:18220/v1
PRIMARY_EMBED_BASE_URL=http://127.0.0.1:18221/v1
AUX_EMBED_BASE_URL=http://127.0.0.1:18222/v1

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${WMA_DATASET_ROOT}" in
  /data1/*/AgentEnhance/datasets/raw/worldmemarena/*|/data2/*/AgentEnhance/datasets/raw/worldmemarena/*) ;;
  *) echo "refusing unexpected dataset root" >&2; exit 2 ;;
esac
case "${UNIT_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected unit root" >&2; exit 2 ;;
esac
case "${SERVICE_ROOT}" in
  /data1/*/AgentEnhance/runs/*/services|/data2/*/AgentEnhance/runs/*/services) ;;
  *) echo "refusing unexpected service root" >&2; exit 2 ;;
esac
case "${WAVE2_SEEDED_LAUNCHER}" in
  /data1/*/AgentEnhance/incoming/*/inputs/scripts/run_wma_seeded_wave2.py|/data2/*/AgentEnhance/incoming/*/inputs/scripts/run_wma_seeded_wave2.py) ;;
  *) echo "refusing unexpected Wave-2 launcher" >&2; exit 2 ;;
esac
case "${RUNTIME_GUARD}" in
  /data1/*/AgentEnhance/incoming/*/inputs/scripts/wma_wave2_runtime_guard.py|/data2/*/AgentEnhance/incoming/*/inputs/scripts/wma_wave2_runtime_guard.py) ;;
  *) echo "refusing unexpected runtime guard" >&2; exit 2 ;;
esac
[[ "${SAMPLE_INDEX}" =~ ^[1-9][0-9]*$ ]] && (( SAMPLE_INDEX <= 150 )) || { echo "invalid sample index" >&2; exit 2; }
[[ "${SESSION_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid session count" >&2; exit 2; }
[[ "${QA_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid QA count" >&2; exit 2; }
[[ "${ATTACHMENT_COUNT_EXPECTED}" =~ ^[0-9]+$ ]] || { echo "invalid attachment count" >&2; exit 2; }
[[ "${UNIT_SEED}" =~ ^[0-9]+$ ]] || { echo "invalid unit seed" >&2; exit 2; }
[[ ! -e "${UNIT_ROOT}" ]] || { echo "refusing existing unit root" >&2; exit 4; }

mkdir -p "${UNIT_ROOT}/evidence" "${UNIT_ROOT}/baseline-storage/tmp"
terminal_reject() {
  local code=$?
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${UNIT_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminal_reject EXIT

[[ "$(git -C "${WMA_REPO}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || { echo "source commit mismatch" >&2; exit 3; }
[[ -z "$(git -C "${WMA_REPO}" status --porcelain)" ]] || { echo "source checkout is dirty" >&2; exit 3; }
[[ "$(sha256sum "${WMA_REPO}/eval_framework/config.yaml" | awk '{print $1}')" == "${WMA_CONFIG_SHA256}" ]] || { echo "config digest mismatch" >&2; exit 3; }
[[ "$(sha256sum "${WMA_DATASET_ROOT}/dataset-manifest.json" | awk '{print $1}')" == "${WMA_DATASET_MANIFEST_SHA256}" ]] || { echo "dataset manifest digest mismatch" >&2; exit 3; }
[[ "$(sha256sum "${RUNTIME_GUARD}" | awk '{print $1}')" == "${RUNTIME_GUARD_SHA256}" ]] || { echo "runtime guard digest mismatch" >&2; exit 3; }
[[ "$(sha256sum "${WAVE2_SEEDED_LAUNCHER}" | awk '{print $1}')" == "${WAVE2_SEEDED_LAUNCHER_SHA256}" ]] || { echo "Wave-2 launcher digest mismatch" >&2; exit 3; }
test -f "${SERVICE_ROOT}/SERVICE_READY"
test -f "${SERVICE_ROOT}/evidence/service-contract.json"

profile_json=$("${WMA_ENV}/bin/python" "${RUNTIME_GUARD}" describe --baseline "${BASELINE}")
service_profile=$(printf '%s' "${profile_json}" | jq -r .service_profile)
method_slug=$(printf '%s' "${profile_json}" | jq -r .slug)
primary_model=$(printf '%s' "${profile_json}" | jq -r .primary_embedding_model)
primary_dim=$(printf '%s' "${profile_json}" | jq -r .primary_embedding_dim)
"${WMA_ENV}/bin/python" - "${SERVICE_ROOT}/evidence/service-contract.json" \
  "${service_profile}" "${primary_model}" "${primary_dim}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "SERVICE_READY" or payload.get("service_profile") != sys.argv[2]:
    raise SystemExit("service profile mismatch")
primary = payload.get("primary_embedding", {})
if primary.get("model") != sys.argv[3] or primary.get("dimension") != int(sys.argv[4]):
    raise SystemExit("primary embedding identity mismatch")
if payload.get("allocated_gpu_indices") != [1, 3, 4, 5]:
    raise SystemExit("allocated GPU identity mismatch")
PY
for endpoint in "${CHAT_BASE_URL}" "${PRIMARY_EMBED_BASE_URL}" "${AUX_EMBED_BASE_URL}"; do
  curl -fsS "${endpoint}/models" >/dev/null
done

chat_log=${SERVICE_ROOT}/logs/chat.log
primary_log=${SERVICE_ROOT}/logs/primary-embedding.log
aux_log=${SERVICE_ROOT}/logs/aux-embedding.log
for log in "${chat_log}" "${primary_log}" "${aux_log}"; do test -f "${log}"; done
chat_offset=$(stat -c%s "${chat_log}")
primary_offset=$(stat -c%s "${primary_log}")
aux_offset=$(stat -c%s "${aux_log}")

python_path="${WMA_REPO}"
if [[ "${BASELINE}" == "Omni-SimpleMem" ]]; then
  : "${SIMPLEMEM_OVERLAY:?Omni-SimpleMem requires SIMPLEMEM_OVERLAY}"
  simplemem_source="${WMA_REPO}/eval_framework/baselines/SimpleMem"
  python_path="${SIMPLEMEM_OVERLAY}:${simplemem_source}:${WMA_REPO}"
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
cat >"${UNIT_ROOT}/evidence/identity.txt" <<EOF
source_commit=${SOURCE_COMMIT}
config_sha256=${WMA_CONFIG_SHA256}
dataset_manifest_sha256=${WMA_DATASET_MANIFEST_SHA256}
baseline=${BASELINE}
method_slug=${method_slug}
service_profile=${service_profile}
primary_embedding_model=${primary_model}
primary_embedding_dim=${primary_dim}
sample_index=${SAMPLE_INDEX}
sample_id=${SAMPLE_ID_EXPECTED}
sessions_expected=${SESSION_COUNT_EXPECTED}
qa_expected=${QA_COUNT_EXPECTED}
attachments_expected=${ATTACHMENT_COUNT_EXPECTED}
unit_seed=${UNIT_SEED}
answer_model=Qwen3-VL-8B-Instruct
answer_model_ctx=128000
service_max_model_len=131072
retrieval_top_k=10
answer_evidence_mode=memory
memory_accuracy_itemwise=true
max_eval_workers=1
allocated_gpu_indices=1,3,4,5
EOF
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  >"${UNIT_ROOT}/evidence/gpu-before.csv"

set +e
(
  cd "${WMA_REPO}"
  env \
    "${extra_env[@]}" \
    CUDA_VISIBLE_DEVICES='' \
    PYTHONHASHSEED="${UNIT_SEED}" \
    PYTHONPATH="$(dirname "${RUNTIME_GUARD}"):${python_path}" \
    AGENTENHANCE_WMA_REPO="${WMA_REPO}" \
    OPENAI_API_KEY=EMPTY \
    OPENAI_MODEL=Qwen3-VL-8B-Instruct \
    OPENAI_BASE_URL="${CHAT_BASE_URL}" \
    OPENAI_TEMPERATURE=0 \
    OPENAI_TIMEOUT=600 \
    LLM_MAX_CONCURRENT=1 \
    OPENAI_EMBEDDING_MODEL="${primary_model}" \
    OPENAI_EMBEDDING_BASE_URL="${PRIMARY_EMBED_BASE_URL}" \
    LOCAL_EMBEDDING_DIMS="${primary_dim}" \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HUB_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    TMPDIR="${UNIT_ROOT}/baseline-storage/tmp" \
    SIMPLEMEM_LANCEDB_PATH="${UNIT_ROOT}/baseline-storage/lancedb" \
    OMNI_MEMORY_DATA_DIR="${UNIT_ROOT}/baseline-storage/omni_memory" \
    EVAL_FRAMEWORK_BASELINE_STORAGE_DIR="${UNIT_ROOT}/baseline-storage/framework" \
    /usr/bin/time -v -o "${UNIT_ROOT}/resource-usage.txt" \
    "${WMA_ENV}/bin/python" "${WAVE2_SEEDED_LAUNCHER}" \
      --unit-seed "${UNIT_SEED}" \
      --baseline "${BASELINE}" \
      --dataset "${WMA_DATASET_ROOT}" \
      --dataset-type worldmemarena \
      --split small \
      --output-dir "${UNIT_ROOT}/output" \
      --sample-index "${SAMPLE_INDEX}" \
      --answer-evidence-mode memory \
      --memory-accuracy-itemwise \
      --max-eval-workers 1
) >"${UNIT_ROOT}/run.log" 2>&1
run_status=$?
set -e

capture_log_delta() {
  local source=$1 offset=$2 destination=$3 size
  size=$(stat -c%s "${source}")
  (( size >= offset )) || { echo "service log shrank during unit" >&2; return 1; }
  tail -c "+$((offset + 1))" "${source}" >"${destination}"
}
capture_log_delta "${chat_log}" "${chat_offset}" "${UNIT_ROOT}/evidence/chat-service.log"
capture_log_delta "${primary_log}" "${primary_offset}" "${UNIT_ROOT}/evidence/primary-embedding-service.log"
capture_log_delta "${aux_log}" "${aux_offset}" "${UNIT_ROOT}/evidence/aux-embedding-service.log"

(( run_status == 0 )) || { echo "Wave-2 runner exited ${run_status}" >&2; exit "${run_status}"; }
grep -q 'AGENTENHANCE_WAVE2_RUNTIME_GUARD=' "${UNIT_ROOT}/run.log"
if [[ "${BASELINE}" == MIRIX ]]; then
  grep -q 'AGENTENHANCE_MIRIX_ENDPOINT_GUARD_ACTIVE=' "${UNIT_ROOT}/run.log"
fi
if [[ "${BASELINE}" == Qwen3-VL-Embedding-8B ]]; then
  grep -q '"qwen_remote_images": "1"' "${UNIT_ROOT}/run.log"
fi
! grep -Eq 'Traceback \(most recent call last\)|CUDA out of memory|Error analyzing content:|\[Omni-SimpleMem\] add_text failed|\[Omni-SimpleMem\] add_image\(.+\) failed' "${UNIT_ROOT}/run.log"
for log in "${UNIT_ROOT}/evidence/chat-service.log" "${UNIT_ROOT}/evidence/primary-embedding-service.log" "${UNIT_ROOT}/evidence/aux-embedding-service.log"; do
  ! grep -Eq 'HTTP/[0-9.]+" [45][0-9][0-9]|CUDA out of memory|Traceback \(most recent call last\)' "${log}"
done

test -s "${UNIT_ROOT}/output/aggregate_metrics.json"
test -s "${UNIT_ROOT}/output/session_records.jsonl"
test -s "${UNIT_ROOT}/output/qa_records.jsonl"
[[ "$(jq -r '.sample_id' "${UNIT_ROOT}/output/session_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]]
[[ "$(jq -r '.sample_id' "${UNIT_ROOT}/output/qa_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]]
[[ "$(wc -l <"${UNIT_ROOT}/output/session_records.jsonl" | tr -d '[:space:]')" == "${SESSION_COUNT_EXPECTED}" ]]
[[ "$(wc -l <"${UNIT_ROOT}/output/qa_records.jsonl" | tr -d '[:space:]')" == "${QA_COUNT_EXPECTED}" ]]

finished_at=$(date -Is)
printf 'baseline\tsample_index\tsample_id\tstarted_at\tfinished_at\n%s\t%s\t%s\t%s\t%s\n' \
  "${BASELINE}" "${SAMPLE_INDEX}" "${SAMPLE_ID_EXPECTED}" "${started_at}" "${finished_at}" \
  >"${UNIT_ROOT}/timing.tsv"
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  >"${UNIT_ROOT}/evidence/gpu-after.csv"
find "${UNIT_ROOT}" -type f ! -name SHA256SUMS ! -name TERMINAL_ACCEPTED ! -name TERMINAL_REJECTED -print0 \
  | sort -z | xargs -0 sha256sum >"${UNIT_ROOT}/SHA256SUMS"
touch "${UNIT_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
printf 'TERMINAL_ACCEPTED baseline=%s sample_index=%s sample_id=%s\n' \
  "${BASELINE}" "${SAMPLE_INDEX}" "${SAMPLE_ID_EXPECTED}"
