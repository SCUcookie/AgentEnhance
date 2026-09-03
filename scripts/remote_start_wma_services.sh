#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE_RUN_ROOT:?set SERVICE_RUN_ROOT to a new project-owned run directory}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

INFER_PYTHON=${INFER_PYTHON:-/data1/anaconda3/envs/clo-infer/bin/python}
CHAT_SESSION=${CHAT_SESSION:-agentenhance-wma-chat-r1}
EMBED1024_SESSION=${EMBED1024_SESSION:-agentenhance-wma-embed1024-r1}
EMBED384_SESSION=${EMBED384_SESSION:-agentenhance-wma-embed384-r1}
CHAT_MAX_MODEL_LEN=${CHAT_MAX_MODEL_LEN:-32768}
CHAT_MAX_NUM_SEQS=${CHAT_MAX_NUM_SEQS:-8}
CHAT_GPU_MEMORY_UTILIZATION=${CHAT_GPU_MEMORY_UTILIZATION:-0.90}

case "${SERVICE_RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected service run root" >&2; exit 2 ;;
esac
case "${CHAT_MODEL_PATH}" in
  /data1/*/AgentEnhance/checkpoints/base-models/qwen3-vl-8b-instruct/rev-5d854aab08710c16b980ec6d603d863b3821b915) ;;
  *) echo "refusing unexpected chat model path" >&2; exit 2 ;;
esac
case "${EMBED_MODEL_PATH}" in
  /data1/*/AgentEnhance/checkpoints/base-models/qwen3-vl-embedding-2b/rev-c35dddf20620fe32745cb3d01f87ba64ae316313) ;;
  *) echo "refusing unexpected embedding model path" >&2; exit 2 ;;
esac
for session in "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"; do
  [[ "${session}" =~ ^agentenhance-wma-[a-zA-Z0-9._-]+$ ]] || { echo "unsafe tmux session name" >&2; exit 2; }
  ! tmux has-session -t "${session}" 2>/dev/null || { echo "tmux session already exists: ${session}" >&2; exit 3; }
done
for port in 18120 18113 18114; do
  ! ss -ltn | awk '{print $4}' | grep -Eq ":${port}$" || { echo "port already in use: ${port}" >&2; exit 3; }
done
for gpu in 1 3 4 5; do
  used=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F',' -v wanted="${gpu}" '$1 + 0 == wanted {gsub(/ /, "", $2); print $2}')
  [[ -n "${used}" && "${used}" -le 100 ]] || { echo "GPU ${gpu} is not free enough: ${used:-unknown} MiB" >&2; exit 3; }
done
test -x "${INFER_PYTHON}"
test -d "${CHAT_MODEL_PATH}"
test -d "${EMBED_MODEL_PATH}"
test ! -e "${SERVICE_RUN_ROOT}"
[[ "${CHAT_MAX_MODEL_LEN}" =~ ^[0-9]+$ ]] || { echo "invalid CHAT_MAX_MODEL_LEN" >&2; exit 2; }
(( CHAT_MAX_MODEL_LEN >= 32768 && CHAT_MAX_MODEL_LEN <= 131072 )) || {
  echo "CHAT_MAX_MODEL_LEN must be in [32768, 131072]" >&2; exit 2;
}
[[ "${CHAT_MAX_NUM_SEQS}" =~ ^[0-9]+$ ]] || { echo "invalid CHAT_MAX_NUM_SEQS" >&2; exit 2; }
(( CHAT_MAX_NUM_SEQS >= 1 && CHAT_MAX_NUM_SEQS <= 8 )) || {
  echo "CHAT_MAX_NUM_SEQS must be in [1, 8]" >&2; exit 2;
}
case "${CHAT_GPU_MEMORY_UTILIZATION}" in
  0.90|0.91|0.92|0.93|0.94|0.95) ;;
  *) echo "CHAT_GPU_MEMORY_UTILIZATION must be one of 0.90..0.95" >&2; exit 2 ;;
esac
mkdir -p "${SERVICE_RUN_ROOT}/logs" "${SERVICE_RUN_ROOT}/evidence"

launch() {
  local session=$1 gpu_ids=$2 log_path=$3
  shift 3
  local command_string quoted_log
  printf -v command_string '%q ' env "CUDA_VISIBLE_DEVICES=${gpu_ids}" "$@"
  printf -v quoted_log '%q' "${log_path}"
  command_string+=" >${quoted_log} 2>&1"
  printf '%s\n' "${command_string}" >"${SERVICE_RUN_ROOT}/evidence/${session}.command.txt"
  tmux new-session -d -s "${session}" bash -lc "exec ${command_string}"
}

launch "${CHAT_SESSION}" "3,4" "${SERVICE_RUN_ROOT}/logs/chat.log" \
  "${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 18120 \
  --model "${CHAT_MODEL_PATH}" --served-model-name Qwen3-VL-8B-Instruct \
  --tensor-parallel-size 2 --max-model-len "${CHAT_MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${CHAT_GPU_MEMORY_UTILIZATION}" \
  --max-num-seqs "${CHAT_MAX_NUM_SEQS}" \
  --limit-mm-per-prompt '{"image":5,"video":0}' --trust-remote-code

launch "${EMBED1024_SESSION}" "1" "${SERVICE_RUN_ROOT}/logs/embed1024.log" \
  "${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 18113 \
  --model "${EMBED_MODEL_PATH}" --served-model-name text-embedding-3-small \
  --runner pooling --convert embed --tensor-parallel-size 1 --max-model-len 8192 \
  --gpu-memory-utilization 0.55 --max-num-seqs 8 \
  --hf-overrides '{"is_matryoshka":true}' \
  --pooler-config '{"dimensions":1024,"normalize":true}' \
  --limit-mm-per-prompt '{"image":1}' --trust-remote-code

launch "${EMBED384_SESSION}" "5" "${SERVICE_RUN_ROOT}/logs/embed384.log" \
  "${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 18114 \
  --model "${EMBED_MODEL_PATH}" --served-model-name text-embedding-3-small \
  --runner pooling --convert embed --tensor-parallel-size 1 --max-model-len 8192 \
  --gpu-memory-utilization 0.55 --max-num-seqs 8 \
  --hf-overrides '{"is_matryoshka":true}' \
  --pooler-config '{"dimensions":384,"normalize":true}' \
  --limit-mm-per-prompt '{"image":1}' --trust-remote-code

wait_for_models() {
  local endpoint=$1 output=$2
  for _ in $(seq 1 180); do
    if curl -fsS "${endpoint}/models" >"${output}"; then
      return 0
    fi
    sleep 5
  done
  return 1
}

wait_for_models http://127.0.0.1:18120/v1 "${SERVICE_RUN_ROOT}/evidence/chat-models.json"
wait_for_models http://127.0.0.1:18113/v1 "${SERVICE_RUN_ROOT}/evidence/embed1024-models.json"
wait_for_models http://127.0.0.1:18114/v1 "${SERVICE_RUN_ROOT}/evidence/embed384-models.json"

curl -fsS http://127.0.0.1:18120/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3-VL-8B-Instruct","temperature":0,"messages":[{"role":"user","content":"Return exactly READY."}],"max_tokens":16}' \
  >"${SERVICE_RUN_ROOT}/evidence/chat-smoke.json"
curl -fsS http://127.0.0.1:18113/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"text-embedding-3-small","input":"service health check"}' \
  >"${SERVICE_RUN_ROOT}/evidence/embed1024-smoke.json"
curl -fsS http://127.0.0.1:18114/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"text-embedding-3-small","input":"service health check"}' \
  >"${SERVICE_RUN_ROOT}/evidence/embed384-smoke.json"

python3 - "${SERVICE_RUN_ROOT}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "evidence"
chat = json.loads((root / "chat-smoke.json").read_text())
assert chat["choices"][0]["message"]["content"]
for name, expected in (("embed1024-smoke.json", 1024), ("embed384-smoke.json", 384)):
    payload = json.loads((root / name).read_text())
    assert len(payload["data"][0]["embedding"]) == expected
PY

cat >"${SERVICE_RUN_ROOT}/evidence/chat-runtime-config.txt" <<EOF
CHAT_MAX_MODEL_LEN=${CHAT_MAX_MODEL_LEN}
CHAT_MAX_NUM_SEQS=${CHAT_MAX_NUM_SEQS}
CHAT_GPU_MEMORY_UTILIZATION=${CHAT_GPU_MEMORY_UTILIZATION}
EOF

nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader >"${SERVICE_RUN_ROOT}/evidence/gpu-ready.csv"
find "${SERVICE_RUN_ROOT}/evidence" -type f -print0 | sort -z | xargs -0 sha256sum \
  >"${SERVICE_RUN_ROOT}/evidence/SHA256SUMS"
touch "${SERVICE_RUN_ROOT}/SERVICE_READY"
printf 'READY chat=%s embed1024=%s embed384=%s\n' \
  "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"
