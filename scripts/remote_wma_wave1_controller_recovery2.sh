#!/usr/bin/env bash
set -euo pipefail

: "${PARENT_CONTROLLER:?set PARENT_CONTROLLER to the immutable recovery1 controller}"
: "${RECOVERY_FULL_SCRIPT:?set RECOVERY_FULL_SCRIPT}"
: "${WMA_ENV:?set WMA_ENV}"

PARENT_SHA256=cb657cdd1a5d18c23b095532397f0072b8e31b8c0327ef4e620d69cd07d339ad
RECOVERY_FULL_SHA256=2df8a4eee3b0a3c121fea863e7f555d55ee2c50646c1cbf7d51700c6e0b1793b
RENDERED_SHA256=b67f34976709142f639cbed65c8b0f4cec241596db1f7d2ef11464d2dc1146be

case "${PARENT_CONTROLLER}" in
  /data1/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_wave1_controller.sh|\
  /data2/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_wave1_controller.sh) ;;
  *) echo "refusing unexpected parent controller" >&2; exit 2 ;;
esac
case "${RECOVERY_FULL_SCRIPT}" in
  /data1/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_full_method_recovery2.sh|\
  /data2/*/AgentEnhance/incoming/*/inputs/scripts/remote_wma_full_method_recovery2.sh) ;;
  *) echo "refusing unexpected recovery full scheduler" >&2; exit 2 ;;
esac
[[ "$(sha256sum "${PARENT_CONTROLLER}" | awk '{print $1}')" == "${PARENT_SHA256}" ]] || {
  echo "parent controller digest mismatch" >&2; exit 3;
}
[[ "$(sha256sum "${RECOVERY_FULL_SCRIPT}" | awk '{print $1}')" == "${RECOVERY_FULL_SHA256}" ]] || {
  echo "recovery full scheduler digest mismatch" >&2; exit 3;
}
test -x "${WMA_ENV}/bin/python"

rendered=$(mktemp /tmp/agentenhance-wma-controller-recovery2.XXXXXX.sh)
cleanup() { rm -f "${rendered}"; }
trap cleanup EXIT
"${WMA_ENV}/bin/python" -c '
import sys
from pathlib import Path
source = Path(sys.argv[1]).read_text(encoding="utf-8")
full_sha = sys.argv[3]
replacements = [
    (
        "FULL_SCHEDULER_SHA256=8f83e3522c07bf9eaca7ab38b056723d7dbd9ac1ba1dc57223f7f08b7ab0bca9",
        f"FULL_SCHEDULER_SHA256={full_sha}",
    ),
    (
        "full_scheduler=\"${PACKAGE_ROOT}/inputs/scripts/remote_wma_full_method.sh\"",
        "full_scheduler=\"${RECOVERY_FULL_SCRIPT}\"",
    ),
    (
        "run_id=\"wma-r1-full-${slug}-seed${seed}-20260903-v1\"",
        "run_id=\"wma-r1-full-${slug}-seed${seed}-recovery2-20260904-v1\"",
    ),
    (
        "session_suffix=\"full-${session_slug}-s${seed}-v1\"",
        "session_suffix=\"full-${session_slug}-s${seed}-r2-v1\"",
    ),
]
for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit(f"expected one frozen controller token: {old}")
    source = source.replace(old, new)
anchor = ">\"${CONTROLLER_ROOT}/identity.txt\"\n\nmethods=(MMFU_Single SimpleMem M2A ViLoMem)"
addition = (
    ">\"${CONTROLLER_ROOT}/identity.txt\"\n"
    "printf '\''recovery_controller=remote_wma_wave1_controller_recovery2.sh\\n"
    f"recovery_full_scheduler_sha256={full_sha}\\n"
    "chat_gpu_memory_utilization=0.90\\nparent_evidence_reused=false\\n'\'' "
    ">>\"${CONTROLLER_ROOT}/identity.txt\"\n\n"
    "methods=(MMFU_Single SimpleMem M2A ViLoMem)"
)
if source.count(anchor) != 1:
    raise SystemExit("expected one controller identity anchor")
Path(sys.argv[2]).write_text(source.replace(anchor, addition), encoding="utf-8")
' "${PARENT_CONTROLLER}" "${rendered}" "${RECOVERY_FULL_SHA256}"
[[ "$(sha256sum "${rendered}" | awk '{print $1}')" == "${RENDERED_SHA256}" ]] || {
  echo "rendered recovery2 controller digest mismatch" >&2; exit 3;
}
bash "${rendered}"
