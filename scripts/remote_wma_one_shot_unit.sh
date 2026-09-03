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
: "${SIMPLEMEM_OVERLAY:?set SIMPLEMEM_OVERLAY}"
: "${VILOMEM_OVERLAY:?set VILOMEM_OVERLAY}"

SOURCE_COMMIT=15ea25b723d9c4fb35e8062037aec6a5601e4442

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
case "${BASELINE}" in
  SimpleMem|ViLoMem|M2A|MMFU_Single) ;;
  *) echo "unsupported baseline: ${BASELINE}" >&2; exit 2 ;;
esac
[[ "${SAMPLE_INDEX}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid sample index" >&2; exit 2; }
(( SAMPLE_INDEX <= 150 )) || { echo "sample index exceeds frozen split" >&2; exit 2; }
[[ "${SESSION_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid session count" >&2; exit 2; }
[[ "${QA_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid QA count" >&2; exit 2; }
[[ ! -e "${UNIT_ROOT}" ]] || { echo "refusing existing unit root: ${UNIT_ROOT}" >&2; exit 4; }

mkdir -p "${UNIT_ROOT}/evidence"
terminal_reject() {
  local code=$?
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" >"${UNIT_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminal_reject EXIT

[[ "$(git -C "${WMA_REPO}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || {
  echo "WorldMemArena source commit mismatch" >&2; exit 3;
}
[[ -z "$(git -C "${WMA_REPO}" status --porcelain)" ]] || {
  echo "WorldMemArena source checkout is dirty" >&2; exit 3;
}
[[ "$(sha256sum "${WMA_REPO}/eval_framework/config.yaml" | awk '{print $1}')" == "${WMA_CONFIG_SHA256}" ]] || {
  echo "WorldMemArena config digest mismatch" >&2; exit 3;
}
[[ "$(sha256sum "${WMA_DATASET_ROOT}/dataset-manifest.json" | awk '{print $1}')" == "${WMA_DATASET_MANIFEST_SHA256}" ]] || {
  echo "dataset manifest digest mismatch" >&2; exit 3;
}
for endpoint in http://127.0.0.1:18120/v1/models http://127.0.0.1:18113/v1/models http://127.0.0.1:18114/v1/models; do
  curl -fsS "${endpoint}" >/dev/null
done

chat_base_url=${WMA_CHAT_BASE_URL:-http://127.0.0.1:18120/v1}
embedding_base_url=${WMA_EMBED1024_BASE_URL:-http://127.0.0.1:18113/v1}
if [[ "${BASELINE}" == "M2A" ]]; then
  embedding_base_url=${WMA_EMBED384_BASE_URL:-http://127.0.0.1:18114/v1}
fi

simplemem_source="${WMA_REPO}/eval_framework/baselines/SimpleMem"
vilomem_source="${WMA_REPO}/eval_framework/baselines/ViLoMem"
python_path="${WMA_REPO}"
if [[ "${BASELINE}" == "SimpleMem" ]]; then
  python_path="${SIMPLEMEM_OVERLAY}:${simplemem_source}:${WMA_REPO}"
elif [[ "${BASELINE}" == "ViLoMem" ]]; then
  python_path="${VILOMEM_OVERLAY}:${vilomem_source}/src:${vilomem_source}:${WMA_REPO}"
fi

started_at=$(date -Is)
cat >"${UNIT_ROOT}/evidence/identity.txt" <<EOF
source_commit=${SOURCE_COMMIT}
config_sha256=${WMA_CONFIG_SHA256}
dataset_manifest_sha256=${WMA_DATASET_MANIFEST_SHA256}
baseline=${BASELINE}
sample_index=${SAMPLE_INDEX}
sample_id=${SAMPLE_ID_EXPECTED}
sessions_expected=${SESSION_COUNT_EXPECTED}
qa_expected=${QA_COUNT_EXPECTED}
answer_model=Qwen3-VL-8B-Instruct
answer_model_ctx=128000
service_max_model_len=131072
retrieval_top_k=10
answer_evidence_mode=memory
memory_accuracy_itemwise=true
max_eval_workers=1
EOF
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  >"${UNIT_ROOT}/evidence/gpu-before.csv"

(
  cd "${WMA_REPO}"
  env \
    CUDA_VISIBLE_DEVICES='' \
    PYTHONPATH="${python_path}" \
    OPENAI_API_KEY="${OPENAI_API_KEY:-EMPTY}" \
    OPENAI_MODEL=Qwen3-VL-8B-Instruct \
    OPENAI_BASE_URL="${chat_base_url}" \
    OPENAI_TEMPERATURE=0 \
    OPENAI_TIMEOUT=600 \
    LLM_MAX_CONCURRENT=1 \
    OPENAI_EMBEDDING_MODEL=text-embedding-3-small \
    OPENAI_EMBEDDING_BASE_URL="${embedding_base_url}" \
    LOCAL_EMBEDDING_DIMS=384 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    SIMPLEMEM_LANCEDB_PATH="${UNIT_ROOT}/baseline-storage/lancedb" \
    OMNI_MEMORY_DATA_DIR="${UNIT_ROOT}/baseline-storage/omni_memory" \
    EVAL_FRAMEWORK_BASELINE_STORAGE_DIR="${UNIT_ROOT}/baseline-storage/framework" \
    /usr/bin/time -v "${WMA_ENV}/bin/python" -m eval_framework.cli \
      --dataset "${WMA_DATASET_ROOT}" \
      --dataset-type worldmemarena \
      --split small \
      --baseline "${BASELINE}" \
      --output-dir "${UNIT_ROOT}/output" \
      --sample-index "${SAMPLE_INDEX}" \
      --answer-evidence-mode memory \
      --memory-accuracy-itemwise \
      --max-eval-workers 1
) >"${UNIT_ROOT}/run.log" 2>"${UNIT_ROOT}/resource-usage.txt"

test -s "${UNIT_ROOT}/output/aggregate_metrics.json"
test -s "${UNIT_ROOT}/output/session_records.jsonl"
test -s "${UNIT_ROOT}/output/qa_records.jsonl"
! grep -q 'Traceback (most recent call last)' "${UNIT_ROOT}/run.log"
[[ "$(jq -r '.sample_id' "${UNIT_ROOT}/output/session_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]]
[[ "$(jq -r '.sample_id' "${UNIT_ROOT}/output/qa_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]]
[[ "$(wc -l <"${UNIT_ROOT}/output/session_records.jsonl" | tr -d '[:space:]')" == "${SESSION_COUNT_EXPECTED}" ]]
[[ "$(wc -l <"${UNIT_ROOT}/output/qa_records.jsonl" | tr -d '[:space:]')" == "${QA_COUNT_EXPECTED}" ]]
if [[ "${BASELINE}" == "SimpleMem" ]]; then
  grep -q 'FTS index created' "${UNIT_ROOT}/run.log"
  ! grep -q 'Error during keyword search' "${UNIT_ROOT}/run.log"
fi

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
