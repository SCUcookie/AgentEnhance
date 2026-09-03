#!/usr/bin/env bash
set -euo pipefail

: "${WMA_REPO:?set WMA_REPO to the frozen WorldMemArena checkout}"
: "${WMA_ENV:?set WMA_ENV to the frozen Python environment}"
: "${RUN_ROOT:?set RUN_ROOT to a new project-owned run directory}"
: "${BASELINE:?set BASELINE}"
: "${CHECK_SCRIPT:?set CHECK_SCRIPT}"
: "${SIMPLEMEM_OVERLAY:?set SIMPLEMEM_OVERLAY}"
: "${VILOMEM_OVERLAY:?set VILOMEM_OVERLAY}"

case "${WMA_REPO}" in
  /data1/*/AgentEnhance/third_party/*/worldmemarena|/data2/*/AgentEnhance/third_party/*/worldmemarena) ;;
  *) echo "refusing unexpected WorldMemArena checkout" >&2; exit 2 ;;
esac
case "${RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected run root" >&2; exit 2 ;;
esac
case "${BASELINE}" in
  SimpleMem|ViLoMem|M2A|MMFU_Single) ;;
  *) echo "unsupported baseline: ${BASELINE}" >&2; exit 2 ;;
esac

method_slug=$(printf '%s' "${BASELINE}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '-')
method_root="${RUN_ROOT}/${method_slug}"
[[ ! -e "${method_root}" ]] || { echo "refusing existing method root: ${method_root}" >&2; exit 3; }
mkdir -p "${method_root}"

chat_base_url=${WMA_CHAT_BASE_URL:-http://127.0.0.1:18120/v1}
embed1024_base_url=${WMA_EMBED1024_BASE_URL:-http://127.0.0.1:18113/v1}
embed384_base_url=${WMA_EMBED384_BASE_URL:-http://127.0.0.1:18114/v1}
embedding_base_url=${embed1024_base_url}
if [[ "${BASELINE}" == "M2A" ]]; then
  embedding_base_url=${embed384_base_url}
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
    OPENAI_EMBEDDING_MODEL="${OPENAI_EMBEDDING_MODEL:-text-embedding-3-small}" \
    OPENAI_EMBEDDING_BASE_URL="${embedding_base_url}" \
    LOCAL_EMBEDDING_DIMS=384 \
    SIMPLEMEM_LANCEDB_PATH="${method_root}/lancedb" \
    "${WMA_ENV}/bin/python" "${CHECK_SCRIPT}" \
      --repo-root "${WMA_REPO}" --baseline "${BASELINE}" --lifecycle
) >"${method_root}/lifecycle.log" 2>&1

grep -q '"status": "LIFECYCLE_PASSED"' "${method_root}/lifecycle.log"
if [[ "${BASELINE}" == "SimpleMem" ]]; then
  grep -q 'FTS index created' "${method_root}/lifecycle.log"
  ! grep -q 'Error during keyword search' "${method_root}/lifecycle.log"
fi

finished_at=$(date -Is)
printf 'baseline\tstarted_at\tfinished_at\n%s\t%s\t%s\n' \
  "${BASELINE}" "${started_at}" "${finished_at}" >"${method_root}/timing.tsv"
find "${method_root}" -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum >"${method_root}/SHA256SUMS"
touch "${method_root}/TERMINAL_ACCEPTED"
tail -n 1 "${method_root}/lifecycle.log"
