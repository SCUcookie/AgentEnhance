#!/usr/bin/env bash
set -euo pipefail

: "${AGENT_ENHANCE_REMOTE_ROOT:?set AGENT_ENHANCE_REMOTE_ROOT}"
: "${SOURCE_RUN_ID:?set SOURCE_RUN_ID}"
: "${RUN_ID:?set RUN_ID}"
: "${WHEEL_FILE:?set WHEEL_FILE}"

case "${AGENT_ENHANCE_REMOTE_ROOT}" in
  /data1/*/AgentEnhance|/data2/*/AgentEnhance) ;;
  *) echo "refusing non-project remote root" >&2; exit 2 ;;
esac

image="nvcr.io/nvidia/pytorch:23.08-py3"
expected_image_id="sha256:9ff159797e3da92a9e47362033f2761633b8de374c095fbdf5cf1b9f157d9d54"
expected_wheel_sha="636f8336facf092165e27924f223d3c62ca560b1f2bb5dff7ab7fad265361987"
source_root="${AGENT_ENHANCE_REMOTE_ROOT}/third_party/${SOURCE_RUN_ID}/cmi"
run_root="${AGENT_ENHANCE_REMOTE_ROOT}/runs/${RUN_ID}"
name_prefix="agentenhance-cmi-r1-recovery2"

[[ -d "${source_root}/.git" ]] || { echo "missing frozen CMI source" >&2; exit 3; }
[[ "$(git -C "${source_root}" rev-parse HEAD)" == "65a66cb4347aeeb62a870132269e8a983211e036" ]] || {
  echo "CMI commit mismatch" >&2; exit 4;
}
[[ -z "$(git -C "${source_root}" status --porcelain)" ]] || {
  echo "CMI source is dirty" >&2; exit 5;
}
[[ "$(docker image inspect --format '{{.Id}}' "${image}")" == "${expected_image_id}" ]] || {
  echo "container image mismatch" >&2; exit 6;
}
[[ -f "${WHEEL_FILE}" ]] || { echo "missing offline wheel" >&2; exit 7; }
[[ "$(sha256sum "${WHEEL_FILE}" | awk '{print $1}')" == "${expected_wheel_sha}" ]] || {
  echo "offline wheel checksum mismatch" >&2; exit 8;
}
[[ ! -e "${run_root}" ]] || { echo "refusing existing recovery root" >&2; exit 9; }
[[ -z "$(docker ps -a --filter "name=^/${name_prefix}-" --format '{{.Names}}')" ]] || {
  echo "named recovery container collision" >&2; exit 10;
}

mkdir -p "${run_root}/evidence"
uid_value="$(id -u)"
gid_value="$(id -g)"
started_at="$(date -Is)"
docker image inspect "${image}" >"${run_root}/evidence/container-image.json"
sha256sum "${WHEEL_FILE}" >"${run_root}/evidence/offline-wheel.sha256"

container_run() {
  local suffix="$1"
  shift
  docker run --rm --name "${name_prefix}-${suffix}" --network none \
    --user "${uid_value}:${gid_value}" \
    --tmpfs "/workspace:rw,exec,uid=${uid_value},gid=${gid_value},mode=0755,size=1g" \
    -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp/mplconfig -e OPENAI_API_KEY= \
    -v "${source_root}:/source:ro" -v "${run_root}:/evidence" \
    -v "${WHEEL_FILE}:/wheels/seaborn-0.13.2-py3-none-any.whl:ro" \
    -w /workspace "${image}" bash -lc \
    'python -m pip install --disable-pip-version-check --no-index --no-deps --target /workspace/.deps /wheels/seaborn-0.13.2-py3-none-any.whl && cp -a /source/. /workspace/ && export PYTHONPATH="/workspace/.deps${PYTHONPATH:+:${PYTHONPATH}}" && exec "$@"' bash "$@"
}

container_run dependency python -c 'import seaborn; assert seaborn.__version__ == "0.13.2"; print(seaborn.__version__)' \
  >"${run_root}/evidence/dependency-check.log" 2>&1

container_run pytest python -m pytest -q \
  >"${run_root}/evidence/pytest.log" 2>&1

container_run validate python -m src.benchmark.validate_dataset \
  --input causal_locomo_final_with_history.jsonl \
  --report /evidence/evidence/dataset-validation.json \
  >"${run_root}/evidence/dataset-validation.log" 2>&1

run_smoke() {
  local attempt="$1"
  container_run "${attempt}" python -m src.experiments.run_experiment \
    --config config/default.yaml \
    --dataset causal_locomo_final_with_history.jsonl \
    --max_examples 5 \
    --run_dir "/evidence/${attempt}" \
    --dry_run --skip_llm_judge --deterministic_only --no_cache \
    >"${run_root}/evidence/${attempt}.log" 2>&1
}

run_smoke dry1
run_smoke dry2

for attempt in dry1 dry2; do
  [[ "$(wc -l <"${run_root}/${attempt}/predictions.jsonl")" -eq 35 ]]
  [[ "$(wc -l <"${run_root}/${attempt}/scores.jsonl")" -eq 35 ]]
  [[ "$(wc -l <"${run_root}/${attempt}/failed_examples.jsonl")" -eq 0 ]]
done
cmp "${run_root}/dry1/scores.jsonl" "${run_root}/dry2/scores.jsonl"

python3 - "${run_root}/evidence/dataset-validation.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report["num_records"] == 87, report
assert report["num_valid"] == 87, report
assert report["num_errors"] == 0, report
PY

[[ -z "$(docker ps -a --filter "name=^/${name_prefix}-" --format '{{.Names}}')" ]]
finished_at="$(date -Is)"
printf 'run_id\tstarted_at\tfinished_at\n%s\t%s\t%s\n' \
  "${RUN_ID}" "${started_at}" "${finished_at}" >"${run_root}/evidence/timing.tsv"
find "${run_root}" -type f ! -path "${run_root}/evidence/SHA256SUMS" -print0 \
  | sort -z | xargs -0 sha256sum >"${run_root}/evidence/SHA256SUMS"
touch "${run_root}/TERMINAL_ACCEPTED"
