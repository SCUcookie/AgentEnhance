#!/usr/bin/env bash
set -euo pipefail

: "${PARENT_FULL_SCHEDULER:?set PARENT_FULL_SCHEDULER to the immutable recovery1 scheduler}"
: "${WMA_ENV:?set WMA_ENV}"

PARENT_SHA256=8f83e3522c07bf9eaca7ab38b056723d7dbd9ac1ba1dc57223f7f08b7ab0bca9
RENDERED_SHA256=db7bcdfbe3cdc9f72853de2520a0d2e7cb90b39dbc3f5c66c4ad9ee417db0958

case "${PARENT_FULL_SCHEDULER}" in
  /data1/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_full_method.sh|\
  /data2/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_full_method.sh) ;;
  *) echo "refusing unexpected parent full scheduler" >&2; exit 2 ;;
esac
[[ "$(sha256sum "${PARENT_FULL_SCHEDULER}" | awk '{print $1}')" == "${PARENT_SHA256}" ]] || {
  echo "parent full scheduler digest mismatch" >&2; exit 3;
}
test -x "${WMA_ENV}/bin/python"

rendered=$(mktemp /tmp/agentenhance-wma-full-recovery2.XXXXXX.sh)
cleanup() { rm -f "${rendered}"; }
trap cleanup EXIT
"${WMA_ENV}/bin/python" -c '
import sys
from pathlib import Path
source = Path(sys.argv[1]).read_text(encoding="utf-8")
old = "CHAT_GPU_MEMORY_UTILIZATION=0.95 \\\n"
new = "CHAT_GPU_MEMORY_UTILIZATION=0.90 \\\n"
if source.count(old) != 1:
    raise SystemExit("expected one frozen utilization assignment")
Path(sys.argv[2]).write_text(source.replace(old, new), encoding="utf-8")
' "${PARENT_FULL_SCHEDULER}" "${rendered}"
[[ "$(sha256sum "${rendered}" | awk '{print $1}')" == "${RENDERED_SHA256}" ]] || {
  echo "rendered recovery2 scheduler digest mismatch" >&2; exit 3;
}
bash "${rendered}"
