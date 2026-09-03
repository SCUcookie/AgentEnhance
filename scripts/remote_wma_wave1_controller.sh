#!/usr/bin/env bash
set -euo pipefail

: "${CONTROLLER_ROOT:?set CONTROLLER_ROOT to a fresh project-owned run root}"
: "${RUN_BASE:?set RUN_BASE to the project runs directory}"
: "${PACKAGE_ROOT:?set PACKAGE_ROOT to the frozen full-run package}"
: "${WMA_REPO:?set WMA_REPO}"
: "${WMA_ENV:?set WMA_ENV}"
: "${WMA_DATASET_ROOT:?set WMA_DATASET_ROOT}"
: "${CHAT_MODEL_PATH:?set CHAT_MODEL_PATH}"
: "${EMBED_MODEL_PATH:?set EMBED_MODEL_PATH}"

UNIT_INVENTORY_SHA256=027f2c3f757d99cb098a6e1887ac7bc837f726031368a4c758970ee90db33f39
START_SERVICES_SCRIPT_SHA256=0763c1c1bac4326168ec873181c037f506f41be8e50d0f242a0957aef5eb8b5b
STOP_SERVICES_SCRIPT_SHA256=cc3cb31f83b5917f77831261d73602dc47cdd5e53e84b664a6e0ed45ae923ffe
UNIT_SCRIPT_SHA256=fcff3ee9ccbcc9a58be95cbe0dd9b85ebefb30094f9c67dc97797811d1654d60
SEEDED_LAUNCHER_SHA256=f362f371ea4bdf73f5a4ece64a524d55a27fc95147bcb87308202608de3b1064
FULL_SCHEDULER_SHA256=8f83e3522c07bf9eaca7ab38b056723d7dbd9ac1ba1dc57223f7f08b7ab0bca9
AGGREGATOR_SHA256=addf5e26dd3e4ceb997a74a8e9fd02f3256dff95a0e3b2559eeb4d945547870b

case "${CONTROLLER_ROOT}" in
  /data1/*/AgentEnhance/runs/*|/data2/*/AgentEnhance/runs/*) ;;
  *) echo "refusing unexpected controller root" >&2; exit 2 ;;
esac
case "${RUN_BASE}" in
  /data1/*/AgentEnhance/runs|/data2/*/AgentEnhance/runs) ;;
  *) echo "refusing unexpected run base" >&2; exit 2 ;;
esac
case "${PACKAGE_ROOT}" in
  /data1/*/AgentEnhance/incoming/*|/data2/*/AgentEnhance/incoming/*) ;;
  *) echo "refusing unexpected package root" >&2; exit 2 ;;
esac
[[ ! -e "${CONTROLLER_ROOT}" ]] || { echo "refusing existing controller root" >&2; exit 3; }
(
  cd "${PACKAGE_ROOT}"
  sha256sum -c PACKAGE_SHA256SUMS
)

full_scheduler="${PACKAGE_ROOT}/inputs/scripts/remote_wma_full_method.sh"
aggregator="${PACKAGE_ROOT}/inputs/scripts/aggregate_wma_one_shot_units.py"
start_services="${PACKAGE_ROOT}/inputs/scripts/remote_start_wma_services.sh"
stop_services="${PACKAGE_ROOT}/inputs/scripts/remote_stop_wma_services.sh"
unit_script="${PACKAGE_ROOT}/inputs/scripts/remote_wma_one_shot_unit_v2.sh"
seeded_launcher="${PACKAGE_ROOT}/inputs/scripts/run_wma_seeded.py"
unit_inventory="${PACKAGE_ROOT}/inputs/comparisons/wma-small-run-units.v1.csv"
simplemem_overlay="${PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/simplemem_overlay"
vilomem_overlay="${PACKAGE_ROOT}/inputs/configs/baselines/worldmemarena/vilomem_overlay"

[[ "$(sha256sum "${full_scheduler}" | awk '{print $1}')" == "${FULL_SCHEDULER_SHA256}" ]]
[[ "$(sha256sum "${aggregator}" | awk '{print $1}')" == "${AGGREGATOR_SHA256}" ]]

mkdir -p "${CONTROLLER_ROOT}"
terminalize() {
  local code=$?
  if (( code != 0 )); then
    printf 'exit_code=%s\nfinished_at=%s\n' "${code}" "$(date -Is)" \
      >"${CONTROLLER_ROOT}/TERMINAL_REJECTED"
  fi
  exit "${code}"
}
trap terminalize EXIT

printf 'method,seed,run_id,scheduler_status,aggregate_status,finished_at\n' \
  >"${CONTROLLER_ROOT}/progress.csv"
printf 'started_at=%s\nmethods=MMFU_Single,SimpleMem,M2A,ViLoMem\nseeds=0,1,2\npackage_root=%s\npackage_manifest_sha256=%s\n' \
  "$(date -Is)" "${PACKAGE_ROOT}" "$(sha256sum "${PACKAGE_ROOT}/PACKAGE_SHA256SUMS" | awk '{print $1}')" \
  >"${CONTROLLER_ROOT}/identity.txt"

methods=(MMFU_Single SimpleMem M2A ViLoMem)
slugs=(mmfu_single simplemem m2a vilomem)
for method_index in "${!methods[@]}"; do
  method=${methods[method_index]}
  slug=${slugs[method_index]}
  for seed in 0 1 2; do
    run_id="wma-r1-full-${slug}-seed${seed}-20260903-v1"
    run_root="${RUN_BASE}/${run_id}"
    aggregate_root="${RUN_BASE}/${run_id}-aggregate"
    session_suffix="full-${slug}-s${seed}-v1"

    RUN_ROOT="${run_root}" \
    BASELINE="${method}" \
    METHOD_SLUG="${slug}" \
    UNIT_SEED="${seed}" \
    SESSION_SUFFIX="${session_suffix}" \
    UNIT_INVENTORY="${unit_inventory}" \
    UNIT_INVENTORY_SHA256="${UNIT_INVENTORY_SHA256}" \
    START_SERVICES_SCRIPT="${start_services}" \
    START_SERVICES_SCRIPT_SHA256="${START_SERVICES_SCRIPT_SHA256}" \
    STOP_SERVICES_SCRIPT="${stop_services}" \
    STOP_SERVICES_SCRIPT_SHA256="${STOP_SERVICES_SCRIPT_SHA256}" \
    UNIT_SCRIPT="${unit_script}" \
    UNIT_SCRIPT_SHA256="${UNIT_SCRIPT_SHA256}" \
    WMA_SEEDED_LAUNCHER="${seeded_launcher}" \
    WMA_SEEDED_LAUNCHER_SHA256="${SEEDED_LAUNCHER_SHA256}" \
    WMA_REPO="${WMA_REPO}" \
    WMA_ENV="${WMA_ENV}" \
    WMA_DATASET_ROOT="${WMA_DATASET_ROOT}" \
    SIMPLEMEM_OVERLAY="${simplemem_overlay}" \
    VILOMEM_OVERLAY="${vilomem_overlay}" \
    CHAT_MODEL_PATH="${CHAT_MODEL_PATH}" \
    EMBED_MODEL_PATH="${EMBED_MODEL_PATH}" \
      timeout --signal=TERM --kill-after=5m 48h bash "${full_scheduler}"
    test -f "${run_root}/SCHEDULER_EXECUTION_ACCEPTED"
    test ! -e "${run_root}/SCHEDULER_EXECUTION_WITH_REJECTIONS"

    timeout --signal=TERM --kill-after=1m 4h "${WMA_ENV}/bin/python" "${aggregator}" \
      --wma-repo "${WMA_REPO}" \
      --dataset-root "${WMA_DATASET_ROOT}" \
      --inventory "${unit_inventory}" \
      --inventory-sha256 "${UNIT_INVENTORY_SHA256}" \
      --units-root "${run_root}/units" \
      --output-root "${aggregate_root}" \
      --baseline "${method}" \
      --seed "${seed}"
    test -f "${aggregate_root}/TERMINAL_ACCEPTED"
    test ! -e "${aggregate_root}/TERMINAL_REJECTED"

    printf '%s,%s,%s,ACCEPTED,ACCEPTED,%s\n' \
      "${method}" "${seed}" "${run_id}" "$(date -Is)" >>"${CONTROLLER_ROOT}/progress.csv"
  done
done

find "${CONTROLLER_ROOT}" -type f ! -name SHA256SUMS ! -name 'TERMINAL_*' -print0 \
  | sort -z | xargs -0 sha256sum >"${CONTROLLER_ROOT}/SHA256SUMS"
touch "${CONTROLLER_ROOT}/TERMINAL_ACCEPTED"
trap - EXIT
printf 'wave1 controller accepted at %s\n' "$(date -Is)"
