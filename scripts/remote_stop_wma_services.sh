#!/usr/bin/env bash
set -euo pipefail

: "${SERVICE_RUN_ROOT:?set SERVICE_RUN_ROOT to the project-owned service run directory}"
CHAT_SESSION=${CHAT_SESSION:-agentenhance-wma-chat-r1}
EMBED1024_SESSION=${EMBED1024_SESSION:-agentenhance-wma-embed1024-r1}
EMBED384_SESSION=${EMBED384_SESSION:-agentenhance-wma-embed384-r1}

case "${SERVICE_RUN_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected service run root" >&2; exit 2 ;;
esac
test -d "${SERVICE_RUN_ROOT}/evidence"

for session in "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"; do
  [[ "${session}" =~ ^agentenhance-wma-[a-zA-Z0-9._-]+$ ]] || { echo "unsafe tmux session name" >&2; exit 2; }
  if tmux has-session -t "${session}" 2>/dev/null; then
    test -f "${SERVICE_RUN_ROOT}/evidence/${session}.command.txt" || {
      echo "refusing to stop a session without this run's ownership record: ${session}" >&2; exit 3;
    }
    tmux kill-session -t "${session}"
  fi
done

for _ in $(seq 1 60); do
  any_live=0
  for session in "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"; do
    if tmux has-session -t "${session}" 2>/dev/null; then
      any_live=1
    fi
  done
  [[ "${any_live}" == 0 ]] && break
  sleep 1
done
for session in "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"; do
  ! tmux has-session -t "${session}" 2>/dev/null || { echo "session still alive: ${session}" >&2; exit 3; }
done

nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader >"${SERVICE_RUN_ROOT}/evidence/gpu-after-stop.csv"
touch "${SERVICE_RUN_ROOT}/SERVICE_STOPPED"
printf 'STOPPED chat=%s embed1024=%s embed384=%s\n' \
  "${CHAT_SESSION}" "${EMBED1024_SESSION}" "${EMBED384_SESSION}"
