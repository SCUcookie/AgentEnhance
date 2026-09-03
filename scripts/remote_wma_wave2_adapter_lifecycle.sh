#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO to the frozen WorldMemArena checkout}"
: "${WMA_ENV:?set WMA_ENV to the frozen Python environment}"
: "${RUN_ROOT:?set RUN_ROOT to a new project-owned run directory}"
: "${BASELINE:?set BASELINE}"
: "${CHECK_SCRIPT:?set CHECK_SCRIPT}"
: "${CHECK_SCRIPT_SHA256:?set CHECK_SCRIPT_SHA256}"
: "${IMAGE_PATH:?set IMAGE_PATH}"
: "${IMAGE_SHA256:?set IMAGE_SHA256}"
: "${WMA_CHAT_BASE_URL:?set WMA_CHAT_BASE_URL}"
: "${WMA_EMBED1024_BASE_URL:?set WMA_EMBED1024_BASE_URL}"
: "${WMA_EMBED384_BASE_URL:?set WMA_EMBED384_BASE_URL}"

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected run root" >&2; exit 2 ;;
esac
case "${BASELINE}" in
  MGMemory|A-Mem|Omni-SimpleMem|MIRIX|NGMemory|AUGUSTUSMemory|UniversalRAGMemory|Qwen3-VL-Embedding-8B) ;;
  *) echo "unsupported Wave-2 baseline: ${BASELINE}" >&2; exit 2 ;;
esac

[[ ! -e "${RUN_ROOT}" ]] || { echo "refusing existing run root: ${RUN_ROOT}" >&2; exit 3; }
[[ -x "${WMA_ENV}/bin/python" ]] || { echo "missing frozen Python environment" >&2; exit 3; }
[[ -f "${CHECK_SCRIPT}" ]] || { echo "missing lifecycle checker" >&2; exit 3; }
[[ -f "${IMAGE_PATH}" ]] || { echo "missing fixed lifecycle image" >&2; exit 3; }
printf '%s  %s\n' "${CHECK_SCRIPT_SHA256}" "${CHECK_SCRIPT}" | sha256sum -c -
printf '%s  %s\n' "${IMAGE_SHA256}" "${IMAGE_PATH}" | sha256sum -c -

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

started_at=$(date -Is)
source_commit=$(git -C "${WMA_REPO}" rev-parse HEAD)
source_status=$(git -C "${WMA_REPO}" status --porcelain)
[[ -z "${source_status}" ]] || { echo "frozen source checkout is dirty" >&2; exit 3; }

embedding_base_url=${WMA_EMBED1024_BASE_URL}
expected_embed_dim=1024
case "${BASELINE}" in
  MGMemory)
    embedding_base_url=${WMA_EMBED384_BASE_URL}
    expected_embed_dim=384
    ;;
  MIRIX)
    : "${WMA_EMBED1536_BASE_URL:?MIRIX requires a dedicated 1536-dimensional endpoint}"
    embedding_base_url=${WMA_EMBED1536_BASE_URL}
    expected_embed_dim=1536
    ;;
esac

curl -fsS "${WMA_CHAT_BASE_URL}/models" >"${RUN_ROOT}/evidence/chat-models.json"
curl -fsS "${embedding_base_url}/embeddings" \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer EMPTY' \
  -d '{"model":"text-embedding-3-small","input":"wave two lifecycle health check"}' \
  >"${RUN_ROOT}/evidence/embedding-health.json"
observed_embed_dim=$("${WMA_ENV}/bin/python" -c \
  'import json,sys; print(len(json.load(open(sys.argv[1]))["data"][0]["embedding"]))' \
  "${RUN_ROOT}/evidence/embedding-health.json")
[[ "${observed_embed_dim}" == "${expected_embed_dim}" ]] || {
  echo "embedding dimension mismatch: expected ${expected_embed_dim}, got ${observed_embed_dim}" >&2
  exit 4
}

python_path=${WMA_REPO}
if [[ "${BASELINE}" == "Omni-SimpleMem" ]]; then
  : "${SIMPLEMEM_OVERLAY:?Omni-SimpleMem requires the frozen SimpleMem overlay}"
  simplemem_source="${WMA_REPO}/eval_framework/baselines/SimpleMem"
  python_path="${SIMPLEMEM_OVERLAY}:${simplemem_source}:${WMA_REPO}"
fi

extra_env=()
if [[ "${BASELINE}" == "NGMemory" || "${BASELINE}" == "AUGUSTUSMemory" || "${BASELINE}" == "UniversalRAGMemory" ]]; then
  : "${GME_BASE_URL:?GME baselines require a dedicated endpoint}"
  : "${GME_MODEL:?GME baselines require a frozen served-model name}"
  [[ "${GME_MODEL}" == "gme-Qwen2-VL-2B-Instruct" ]] || {
    echo "unexpected GME served-model name" >&2
    exit 4
  }
  curl -fsS "${GME_BASE_URL}/embeddings" \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer EMPTY' \
    -d "{\"model\":\"${GME_MODEL}\",\"input\":\"wave two GME health check\"}" \
    >"${RUN_ROOT}/evidence/gme-health.json"
  observed_gme_dim=$("${WMA_ENV}/bin/python" -c \
    'import json,sys; print(len(json.load(open(sys.argv[1]))["data"][0]["embedding"]))' \
    "${RUN_ROOT}/evidence/gme-health.json")
  [[ "${observed_gme_dim}" == "1536" ]] || {
    echo "GME dimension mismatch: expected 1536, got ${observed_gme_dim}" >&2
    exit 4
  }
  extra_env+=(GME_BASE_URL="${GME_BASE_URL}" GME_MODEL="${GME_MODEL}" GME_API_KEY=EMPTY)
fi
if [[ "${BASELINE}" == "Qwen3-VL-Embedding-8B" ]]; then
  : "${QWEN_VL_EMBED_BASE_URL:?Qwen3-VL-Embedding-8B requires its dedicated endpoint}"
  : "${QWEN_VL_EMBED_MODEL:?set the exact frozen served-model name}"
  [[ "${QWEN_VL_EMBED_MODEL}" == "Qwen3-VL-Embedding-8B" ]] || {
    echo "unexpected Qwen3-VL embedding served-model name" >&2
    exit 4
  }
  curl -fsS "${QWEN_VL_EMBED_BASE_URL}/embeddings" \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer EMPTY' \
    -d '{"model":"Qwen3-VL-Embedding-8B","input":"wave two Qwen VL health check"}' \
    >"${RUN_ROOT}/evidence/qwen-vl-embedding-health.json"
  observed_qwen_vl_dim=$("${WMA_ENV}/bin/python" -c \
    'import json,sys; print(len(json.load(open(sys.argv[1]))["data"][0]["embedding"]))' \
    "${RUN_ROOT}/evidence/qwen-vl-embedding-health.json")
  [[ "${observed_qwen_vl_dim}" == "4096" ]] || {
    echo "Qwen3-VL embedding dimension mismatch: expected 4096, got ${observed_qwen_vl_dim}" >&2
    exit 4
  }
  extra_env+=(
    QWEN_VL_EMBED_BASE_URL="${QWEN_VL_EMBED_BASE_URL}"
    QWEN_VL_EMBED_MODEL="${QWEN_VL_EMBED_MODEL}"
    QWEN_VL_EMBED_API_KEY=EMPTY
  )
fi

set +e
env \
  "${extra_env[@]}" \
  PYTHONPATH="${python_path}" \
  OPENAI_API_KEY=EMPTY \
  OPENAI_MODEL=Qwen3-VL-8B-Instruct \
  OPENAI_BASE_URL="${WMA_CHAT_BASE_URL}" \
  OPENAI_EMBEDDING_MODEL=text-embedding-3-small \
  OPENAI_EMBEDDING_BASE_URL="${embedding_base_url}" \
  LOCAL_EMBEDDING_DIMS="${expected_embed_dim}" \
  SIMPLEMEM_LANCEDB_PATH="${RUN_ROOT}/simplemem-lancedb" \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  "${WMA_ENV}/bin/python" "${CHECK_SCRIPT}" \
    --repo-root "${WMA_REPO}" \
    --baseline "${BASELINE}" \
    --image-path "${IMAGE_PATH}" \
    --image-sha256 "${IMAGE_SHA256}" \
  >"${RUN_ROOT}/lifecycle.log" 2>"${RUN_ROOT}/lifecycle.stderr"
checker_status=$?
set -e

finished_at=$(date -Is)
printf 'baseline\tstarted_at\tfinished_at\tsource_commit\tembed_dim\tchecker_exit\n%s\t%s\t%s\t%s\t%s\t%s\n' \
  "${BASELINE}" "${started_at}" "${finished_at}" "${source_commit}" \
  "${expected_embed_dim}" "${checker_status}" >"${RUN_ROOT}/timing.tsv"

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
