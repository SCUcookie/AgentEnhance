#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <base-python> <frozen-worldmemarena-repo> <new-venv> <expected-lock-file>" >&2
  exit 64
}

[[ $# -eq 4 ]] || usage
base_python=$1
wma_repo=$2
target_env=$3
expected_lock=$4

[[ -x "${base_python}" ]] || { echo "base Python is not executable" >&2; exit 2; }
[[ -f "${wma_repo}/requirements.txt" ]] || { echo "missing WorldMemArena requirements.txt" >&2; exit 2; }
[[ -f "${expected_lock}" ]] || { echo "missing expected lock file" >&2; exit 2; }
case "${target_env}" in
  /data1/*/AgentEnhance/environments/*|/data2/*/AgentEnhance/environments/*) ;;
  *) echo "refusing unexpected environment target" >&2; exit 2 ;;
esac
[[ ! -e "${target_env}" ]] || { echo "refusing existing environment target" >&2; exit 3; }

"${base_python}" -m venv --system-site-packages "${target_env}"
"${target_env}/bin/python" -m pip install -r "${wma_repo}/requirements.txt"
"${target_env}/bin/python" -m pip install \
  pymilvus==2.6.17 milvus-lite==2.5.1 \
  langchain-qwq==0.3.5 math-verify==0.9.0 dashscope==1.27.3 \
  open-clip-torch==3.3.0 langchain-siliconflow==1.0.0 \
  langchain-tavily==0.2.18 langchain-mcp-adapters==0.3.2 \
  dateparser==1.2.2 lancedb==0.25.3 tantivy==0.26.0 pylance==0.39.0
"${target_env}/bin/python" -m pip check

actual_lock="${target_env}/agentenhance-pip-freeze.txt"
"${target_env}/bin/python" -m pip freeze --all >"${actual_lock}"
if ! cmp "${expected_lock}" "${actual_lock}"; then
  echo "environment resolves cleanly but does not match the accepted lock" >&2
  exit 5
fi
sha256sum "${actual_lock}"
