#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE_RUN_ROOT:?set SERVICE_RUN_ROOT}"
CHAT_SESSION=${CHAT_SESSION:-agentenhance-wma-wave2-chat}
PRIMARY_EMBED_SESSION=${PRIMARY_EMBED_SESSION:-agentenhance-wma-wave2-primary}
AUX_EMBED_SESSION=${AUX_EMBED_SESSION:-agentenhance-wma-wave2-aux}

case "${SERVICE_RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected service run root" >&2; exit 2 ;;
esac
test -f "${SERVICE_RUN_ROOT}/SERVICE_READY"
test -f "${SERVICE_RUN_ROOT}/evidence/service-contract.json"

for session in "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"; do
  [[ "${session}" =~ ^agentenhance-wma-[a-zA-Z0-9._-]+$ ]] || { echo "unsafe tmux session name" >&2; exit 2; }
  if tmux has-session -t "${session}" 2>/dev/null; then
    test -f "${SERVICE_RUN_ROOT}/evidence/${session}.command.txt" || {
      echo "refusing to stop an unowned session: ${session}" >&2; exit 3;
    }
    tmux kill-session -t "${session}"
  fi
done
for _ in $(seq 1 60); do
  any_live=0
  for session in "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"; do
    tmux has-session -t "${session}" 2>/dev/null && any_live=1
  done
  [[ "${any_live}" == 0 ]] && break
  sleep 1
done
for session in "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"; do
  ! tmux has-session -t "${session}" 2>/dev/null || { echo "session still alive: ${session}" >&2; exit 3; }
done
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader >"${SERVICE_RUN_ROOT}/evidence/gpu-after-stop.csv"
touch "${SERVICE_RUN_ROOT}/SERVICE_STOPPED"
printf 'STOPPED chat=%s primary=%s aux=%s\n' \
  "${CHAT_SESSION}" "${PRIMARY_EMBED_SESSION}" "${AUX_EMBED_SESSION}"
