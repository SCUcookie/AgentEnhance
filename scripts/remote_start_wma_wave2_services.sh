#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE_RUN_ROOT:?set SERVICE_RUN_ROOT to a fresh project-owned run directory}"
: "${SERVICE_PROFILE:?set SERVICE_PROFILE}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${SHARED_EMBED_MODEL_PATH:?set SHARED_EMBED_MODEL_PATH}"

INFER_PYTHON=${INFER_PYTHON:-/data1/anaconda3/envs/clo-infer/bin/python3.11}
CHAT_SESSION=${CHAT_SESSION:-agentenhance-wma-wave2-chat}
PRIMARY_EMBED_SESSION=${PRIMARY_EMBED_SESSION:-agentenhance-wma-wave2-primary}
AUX_EMBED_SESSION=${AUX_EMBED_SESSION:-agentenhance-wma-wave2-aux}
CHAT_BASE_URL=http://127.0.0.1:18220/v1
PRIMARY_EMBED_BASE_URL=http://127.0.0.1:18221/v1
AUX_EMBED_BASE_URL=http://127.0.0.1:18222/v1

case "${SERVICE_RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected service run root" >&2; exit 2 ;;
esac
case "${CHAT_MODEL_PATH}" in
  /data1/*/AgentEnhance/checkpoints/base-models/qwen3-vl-8b-instruct/rev-5d854aab08710c16b980ec6d603d863b3821b915) ;;
  *) echo "refusing unexpected chat model path" >&2; exit 2 ;;
esac
case "${SHARED_EMBED_MODEL_PATH}" in
  /data1/*/AgentEnhance/checkpoints/base-models/qwen3-vl-embedding-2b/rev-c35dddf20620fe32745cb3d01f87ba64ae316313) ;;
  *) echo "refusing unexpected shared embedding model path" >&2; exit 2 ;;
esac
case "${SERVICE_PROFILE}" in
  text384)
    primary_model_path=${SHARED_EMBED_MODEL_PATH}
    primary_model_name=text-embedding-3-small
    primary_dim=384
    aux_dim=1024
    primary_kind=shared-matryoshka
    ;;
  text1024)
    primary_model_path=${SHARED_EMBED_MODEL_PATH}
    primary_model_name=text-embedding-3-small
    primary_dim=1024
    aux_dim=384
    primary_kind=shared-matryoshka
    ;;
  text1536)
    primary_model_path=${SHARED_EMBED_MODEL_PATH}
    primary_model_name=text-embedding-3-small
    primary_dim=1536
    aux_dim=384
    primary_kind=shared-matryoshka
    ;;
  gme1536)
    : "${WAVE2_GME_MODEL_PATH:?gme1536 requires WAVE2_GME_MODEL_PATH}"
    : "${WAVE2_GME_MATERIALIZATION_ROOT:?gme1536 requires materialization evidence}"
    primary_model_path=${WAVE2_GME_MODEL_PATH}
    primary_model_name=gme-Qwen2-VL-2B-Instruct
    primary_dim=1536
    aux_dim=384
    primary_kind=gme
    GME_SERVER_LAUNCHER=${GME_SERVER_LAUNCHER:-$(dirname "$0")/run_vllm_gme_guarded.py}
    [[ "$(sha256sum "${GME_SERVER_LAUNCHER}" | awk '{print $1}')" == "232da2e5837a4d1e1536566569002c540b52d95c57f5f39fc3a09f9060a0f787" ]] || {
      echo "GME server launcher digest mismatch" >&2; exit 3;
    }
    ;;
  qwen4096)
    : "${WAVE2_QWEN_MODEL_PATH:?qwen4096 requires WAVE2_QWEN_MODEL_PATH}"
    : "${WAVE2_QWEN_MATERIALIZATION_ROOT:?qwen4096 requires materialization evidence}"
    primary_model_path=${WAVE2_QWEN_MODEL_PATH}
    primary_model_name=Qwen3-VL-Embedding-8B
    primary_dim=4096
    aux_dim=384
    primary_kind=qwen-vl
    ;;
  *) echo "unsupported Wave-2 service profile: ${SERVICE_PROFILE}" >&2; exit 2 ;;
esac

verify_owned_model() {
  local target=$1 evidence_root=$2 expected_repository=$3 expected_revision=$4
  case "${target}" in
    /data1/*/AgentEnhance/cache/models/*|/data2/*/AgentEnhance/cache/models/*) ;;
    *) echo "refusing unexpected project-owned model path" >&2; exit 2 ;;
  esac
  case "${evidence_root}" in
    /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
    *) echo "refusing unexpected materialization root" >&2; exit 2 ;;
  esac
  test -f "${evidence_root}/TERMINAL_ACCEPTED"
  test ! -e "${evidence_root}/TERMINAL_REJECTED"
  test -f "${evidence_root}/model-materialization.json"
  test -f "${evidence_root}/MODEL_SHA256SUMS"
  "${INFER_PYTHON}" - "${target}" "${evidence_root}/model-materialization.json" \
    "${expected_repository}" "${expected_revision}" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
record = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if record.get("status") != "TERMINAL_ACCEPTED":
    raise SystemExit("model materialization is not terminal-accepted")
if Path(record.get("target", "")).resolve() != target:
    raise SystemExit("materialized target mismatch")
if record.get("repository") != sys.argv[3] or record.get("revision") != sys.argv[4]:
    raise SystemExit("materialized repository identity mismatch")
PY
  sha256sum -c "${evidence_root}/MODEL_SHA256SUMS"
}

if [[ "${SERVICE_PROFILE}" == gme1536 ]]; then
  verify_owned_model "${primary_model_path}" "${WAVE2_GME_MATERIALIZATION_ROOT}" \
    Alibaba-NLP/gme-Qwen2-VL-2B-Instruct 9cfa6413f704a7c1cf5064d240748e10c876b286
elif [[ "${SERVICE_PROFILE}" == qwen4096 ]]; then
  verify_owned_model "${primary_model_path}" "${WAVE2_QWEN_MATERIALIZATION_ROOT}" \
    Qwen/Qwen3-VL-Embedding-8B 2c4565515e0f265c6511776e7193b22c0968ddc7
fi

for session in "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"; do
  [[ "${session}" =~ ^agentenhance-wma-[a-zA-Z0-9._-]+$ ]] || { echo "unsafe tmux session name" >&2; exit 2; }
  ! tmux has-session -t "${session}" 2>/dev/null || { echo "tmux session already exists: ${session}" >&2; exit 3; }
done
for port in 18220 18221 18222; do
  ! ss -ltn | awk '{print $4}' | grep -Eq ":${port}$" || { echo "port already in use: ${port}" >&2; exit 3; }
done
for gpu in 1 3 4 5; do
  used=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
    | awk -F',' -v wanted="${gpu}" '$1 + 0 == wanted {gsub(/ /, "", $2); print $2}')
  [[ -n "${used}" && "${used}" -le 100 ]] || { echo "GPU ${gpu} is not free enough: ${used:-unknown} MiB" >&2; exit 3; }
done
test -x "${INFER_PYTHON}"
test -d "${CHAT_MODEL_PATH}"
test -d "${SHARED_EMBED_MODEL_PATH}"
test -d "${primary_model_path}"
test ! -e "${SERVICE_RUN_ROOT}"
mkdir -p "${SERVICE_RUN_ROOT}/logs" "${SERVICE_RUN_ROOT}/evidence"

started_sessions=()
cleanup_failed_start() {
  local status=$?
  if (( status != 0 )); then
    for session in "${started_sessions[@]}"; do
      if [[ -f "${SERVICE_RUN_ROOT}/evidence/${session}.command.txt" ]] \
        && tmux has-session -t "${session}" 2>/dev/null; then
        tmux kill-session -t "${session}" || true
      fi
    done
    printf 'exit_code=%s\nfinished_at=%s\n' "${status}" "$(date -Is)" \
      >"${SERVICE_RUN_ROOT}/SERVICE_START_REJECTED"
  fi
  exit "${status}"
}
trap cleanup_failed_start EXIT

launch() {
  local session=$1 gpu_ids=$2 log_path=$3
  shift 3
  local command_string quoted_log
  printf -v command_string '%q ' env "CUDA_VISIBLE_DEVICES=${gpu_ids}" "$@"
  printf -v quoted_log '%q' "${log_path}"
  command_string+=" >${quoted_log} 2>&1"
  printf '%s\n' "${command_string}" >"${SERVICE_RUN_ROOT}/evidence/${session}.command.txt"
  tmux new-session -d -s "${session}" bash -lc "exec ${command_string}"
  started_sessions+=("${session}")
}

launch "${CHAT_SESSION}" "3,4" "${SERVICE_RUN_ROOT}/logs/chat.log" \
  "${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 18220 \
  --model "${CHAT_MODEL_PATH}" --served-model-name Qwen3-VL-8B-Instruct \
  --tensor-parallel-size 2 --max-model-len 131072 \
  --gpu-memory-utilization 0.90 --max-num-seqs 1 \
  --limit-mm-per-prompt '{"image":5,"video":0}' --trust-remote-code

primary_entry=("${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server)
if [[ "${primary_kind}" == gme ]]; then
  primary_entry=("${INFER_PYTHON}" "${GME_SERVER_LAUNCHER}")
fi
primary_args=(
  "${primary_entry[@]}"
  --host 127.0.0.1 --port 18221
  --model "${primary_model_path}" --served-model-name "${primary_model_name}"
  --runner pooling --convert embed --tensor-parallel-size 1 --max-model-len 8192
  --gpu-memory-utilization 0.90 --max-num-seqs 1
  --limit-mm-per-prompt '{"image":1,"video":0}' --trust-remote-code
)
if [[ "${primary_kind}" == shared-matryoshka ]]; then
  primary_args+=(
    --hf-overrides '{"is_matryoshka":true}'
    --pooler-config "{\"dimensions\":${primary_dim},\"normalize\":true}"
  )
fi
launch "${PRIMARY_EMBED_SESSION}" "1" "${SERVICE_RUN_ROOT}/logs/primary-embedding.log" \
  "${primary_args[@]}"

launch "${AUX_EMBED_SESSION}" "5" "${SERVICE_RUN_ROOT}/logs/aux-embedding.log" \
  "${INFER_PYTHON}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 18222 \
  --model "${SHARED_EMBED_MODEL_PATH}" --served-model-name text-embedding-3-small \
  --runner pooling --convert embed --tensor-parallel-size 1 --max-model-len 8192 \
  --gpu-memory-utilization 0.55 --max-num-seqs 1 \
  --hf-overrides '{"is_matryoshka":true}' \
  --pooler-config "{\"dimensions\":${aux_dim},\"normalize\":true}" \
  --limit-mm-per-prompt '{"image":1,"video":0}' --trust-remote-code

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

wait_for_models "${CHAT_BASE_URL}" "${SERVICE_RUN_ROOT}/evidence/chat-models.json"
wait_for_models "${PRIMARY_EMBED_BASE_URL}" "${SERVICE_RUN_ROOT}/evidence/primary-models.json"
wait_for_models "${AUX_EMBED_BASE_URL}" "${SERVICE_RUN_ROOT}/evidence/aux-models.json"

curl -fsS "${CHAT_BASE_URL}/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3-VL-8B-Instruct","temperature":0,"messages":[{"role":"user","content":"Return exactly READY."}],"max_tokens":16}' \
  >"${SERVICE_RUN_ROOT}/evidence/chat-smoke.json"
if [[ "${primary_kind}" == gme || "${primary_kind}" == qwen-vl ]]; then
  curl -fsS "${PRIMARY_EMBED_BASE_URL}/embeddings" \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer EMPTY' \
    -d "{\"model\":\"${primary_model_name}\",\"messages\":[{\"role\":\"system\",\"content\":[{\"type\":\"text\",\"text\":\"Represent the input for retrieval.\"}]},{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"service health check\"}]},{\"role\":\"assistant\",\"content\":[{\"type\":\"text\",\"text\":\"\"}]}],\"encoding_format\":\"float\",\"continue_final_message\":true,\"add_special_tokens\":true}" \
    >"${SERVICE_RUN_ROOT}/evidence/primary-smoke.json"
else
  curl -fsS "${PRIMARY_EMBED_BASE_URL}/embeddings" \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer EMPTY' \
    -d "{\"model\":\"${primary_model_name}\",\"input\":\"service health check\"}" \
    >"${SERVICE_RUN_ROOT}/evidence/primary-smoke.json"
fi
curl -fsS "${AUX_EMBED_BASE_URL}/embeddings" \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer EMPTY' \
  -d '{"model":"text-embedding-3-small","input":"service health check"}' \
  >"${SERVICE_RUN_ROOT}/evidence/aux-smoke.json"

"${INFER_PYTHON}" - "${SERVICE_RUN_ROOT}" "${SERVICE_PROFILE}" \
  "${primary_model_name}" "${primary_dim}" "${aux_dim}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
profile, model, primary_dim, aux_dim = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
evidence = root / "evidence"
chat = json.loads((evidence / "chat-smoke.json").read_text())
if not chat["choices"][0]["message"]["content"]:
    raise SystemExit("empty chat smoke response")
for name, expected in (("primary-smoke.json", primary_dim), ("aux-smoke.json", aux_dim)):
    payload = json.loads((evidence / name).read_text())
    if len(payload["data"][0]["embedding"]) != expected:
        raise SystemExit(f"embedding dimension mismatch for {name}")
contract = {
    "schema_version": "agentenhance.wma_wave2_service_contract.v1",
    "status": "SERVICE_READY",
    "service_profile": profile,
    "chat": {"base_url": "http://127.0.0.1:18220/v1", "model": "Qwen3-VL-8B-Instruct", "gpus": [3, 4]},
    "primary_embedding": {"base_url": "http://127.0.0.1:18221/v1", "model": model, "dimension": primary_dim, "gpus": [1]},
    "aux_embedding": {"base_url": "http://127.0.0.1:18222/v1", "model": "text-embedding-3-small", "dimension": aux_dim, "gpus": [5]},
    "allocated_gpu_indices": [1, 3, 4, 5],
}
(evidence / "service-contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
PY

nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader >"${SERVICE_RUN_ROOT}/evidence/gpu-ready.csv"
find "${SERVICE_RUN_ROOT}/evidence" -type f -print0 | sort -z | xargs -0 sha256sum \
  >"${SERVICE_RUN_ROOT}/evidence/SHA256SUMS"
touch "${SERVICE_RUN_ROOT}/SERVICE_READY"
trap - EXIT
printf 'READY profile=%s chat=%s primary=%s aux=%s\n' \
  "${SERVICE_PROFILE}" "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"
