#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${WMA_DATASET_MANIFEST_SHA256:?set WMA_DATASET_MANIFEST_SHA256}"
: "${RUN_ROOT:?set RUN_ROOT to a new project-owned run directory}"
: "${BASELINE:?set BASELINE}"
: "${SAMPLE_INDEX:?set SAMPLE_INDEX to a 1-based frozen index}"
: "${SAMPLE_ID_EXPECTED:?set SAMPLE_ID_EXPECTED for the frozen index}"
: "${SESSION_COUNT_EXPECTED:?set SESSION_COUNT_EXPECTED for the frozen sample}"
: "${QA_COUNT_EXPECTED:?set QA_COUNT_EXPECTED for the frozen sample}"
: "${SIMPLEMEM_OVERLAY:?set SIMPLEMEM_OVERLAY}"
: "${VILOMEM_OVERLAY:?set VILOMEM_OVERLAY}"

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${WMA_DATASET_ROOT}" in
  /data1/*/AgentEnhance/datasets/raw/worldmemarena/*|/data2/*/AgentEnhance/datasets/raw/worldmemarena/*) ;;
  *) echo "refusing unexpected dataset root" >&2; exit 2 ;;
esac
case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected run root" >&2; exit 2 ;;
esac
case "${BASELINE}" in
  SimpleMem|ViLoMem|M2A|MMFU_Single) ;;
  *) echo "unsupported baseline: ${BASELINE}" >&2; exit 2 ;;
esac
[[ "${SAMPLE_INDEX}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid sample index" >&2; exit 2; }
[[ "${SESSION_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid expected session count" >&2; exit 2; }
[[ "${QA_COUNT_EXPECTED}" =~ ^[1-9][0-9]*$ ]] || { echo "invalid expected QA count" >&2; exit 2; }

[[ "$(git -C "${WMA_REPO}" rev-parse HEAD)" == "15ea25b723d9c4fb35e8062037aec6a5601e4442" ]] || {
  echo "WorldMemArena source commit mismatch" >&2; exit 3;
}
[[ -z "$(git -C "${WMA_REPO}" status --porcelain)" ]] || {
  echo "WorldMemArena source checkout is dirty" >&2; exit 3;
}
[[ -f "${WMA_DATASET_ROOT}/dataset-manifest.json" ]] || {
  echo "missing dataset manifest" >&2; exit 3;
}
[[ "$(sha256sum "${WMA_DATASET_ROOT}/dataset-manifest.json" | awk '{print $1}')" == "${WMA_DATASET_MANIFEST_SHA256}" ]] || {
  echo "dataset manifest digest mismatch" >&2; exit 3;
}

method_slug=$(printf '%s' "${BASELINE}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '-')
method_root="${RUN_ROOT}/${method_slug}"
[[ ! -e "${method_root}" ]] || { echo "refusing existing method root: ${method_root}" >&2; exit 4; }
mkdir -p "${method_root}"

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
(
  cd "${WMA_REPO}"
  env \
    PYTHONPATH="${python_path}" \
    OPENAI_API_KEY="${OPENAI_API_KEY:-EMPTY}" \
    OPENAI_MODEL="${OPENAI_MODEL:-Qwen3-VL-8B-Instruct}" \
    OPENAI_BASE_URL="${chat_base_url}" \
    OPENAI_TEMPERATURE=0 \
    OPENAI_EMBEDDING_MODEL="${OPENAI_EMBEDDING_MODEL:-text-embedding-3-small}" \
    OPENAI_EMBEDDING_BASE_URL="${embedding_base_url}" \
    LOCAL_EMBEDDING_DIMS=384 \
    SIMPLEMEM_LANCEDB_PATH="${method_root}/lancedb" \
    "${WMA_ENV}/bin/python" -m eval_framework.cli \
      --dataset "${WMA_DATASET_ROOT}" \
      --dataset-type worldmemarena \
      --split small \
      --baseline "${BASELINE}" \
      --output-dir "${method_root}/output" \
      --sample-index "${SAMPLE_INDEX}" \
      --answer-evidence-mode memory \
      --memory-accuracy-itemwise \
      --max-eval-workers 1
) >"${method_root}/run.log" 2>&1

test -s "${method_root}/output/aggregate_metrics.json"
test -s "${method_root}/output/session_records.jsonl"
test -s "${method_root}/output/qa_records.jsonl"
! grep -q 'Traceback (most recent call last)' "${method_root}/run.log"
[[ "$(jq -r '.sample_id' "${method_root}/output/session_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]] || {
  echo "session-record sample ID mismatch" >&2; exit 5;
}
[[ "$(jq -r '.sample_id' "${method_root}/output/qa_records.jsonl" | sort -u)" == "${SAMPLE_ID_EXPECTED}" ]] || {
  echo "QA-record sample ID mismatch" >&2; exit 5;
}
[[ "$(wc -l <"${method_root}/output/session_records.jsonl" | tr -d '[:space:]')" == "${SESSION_COUNT_EXPECTED}" ]] || {
  echo "session-record count mismatch" >&2; exit 5;
}
[[ "$(wc -l <"${method_root}/output/qa_records.jsonl" | tr -d '[:space:]')" == "${QA_COUNT_EXPECTED}" ]] || {
  echo "QA-record count mismatch" >&2; exit 5;
}
if [[ "${BASELINE}" == "SimpleMem" ]]; then
  grep -q 'FTS index created' "${method_root}/run.log"
  ! grep -q 'Error during keyword search' "${method_root}/run.log"
fi

finished_at=$(date -Is)
printf 'baseline\tsample_index\tsample_id\tstarted_at\tfinished_at\n%s\t%s\t%s\t%s\t%s\n' \
  "${BASELINE}" "${SAMPLE_INDEX}" "${SAMPLE_ID_EXPECTED}" "${started_at}" "${finished_at}" >"${method_root}/timing.tsv"
find "${method_root}" -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum >"${method_root}/SHA256SUMS"
touch "${method_root}/TERMINAL_ACCEPTED"
printf 'accepted %s sample-index=%s\n' "${BASELINE}" "${SAMPLE_INDEX}"
