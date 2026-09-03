#!/usr/bin/env bash
set -euo pipefail

: "${AGENT_ENHANCE_REMOTE_ROOT:?set AGENT_ENHANCE_REMOTE_ROOT}"
: "${SOURCE_RUN_ID:?set SOURCE_RUN_ID}"
: "${RUN_ID:?set RUN_ID}"

case "${AGENT_ENHANCE_REMOTE_ROOT}" in
  /data1/*/AgentEnhance|/data2/*/AgentEnhance) ;;
  *) echo "refusing non-project remote root" >&2; exit 2 ;;
esac

image="nvcr.io/nvidia/pytorch:23.08-py3"
expected_image_id="sha256:9ff159797e3da92a9e47362033f2761633b8de374c095fbdf5cf1b9f157d9d54"
source_root="${AGENT_ENHANCE_REMOTE_ROOT}/third_party/${SOURCE_RUN_ID}/cmi"
run_root="${AGENT_ENHANCE_REMOTE_ROOT}/runs/${RUN_ID}"

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
[[ ! -e "${run_root}" ]] || { echo "refusing existing R1 root" >&2; exit 7; }

mkdir -p "${run_root}/evidence" "${run_root}/test-outputs" \
  "${run_root}/test-cache" "${run_root}/dry1-cache" "${run_root}/dry2-cache"
uid_gid="$(id -u):$(id -g)"
started_at="$(date -Is)"
docker image inspect "${image}" >"${run_root}/evidence/container-image.json"

docker run --rm --network none --user "${uid_gid}" \
  -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp/mplconfig -e OPENAI_API_KEY= \
  -v "${source_root}:/workspace:ro" \
  -v "${run_root}/test-outputs:/workspace/outputs" \
  -v "${run_root}/test-cache:/workspace/.cache" \
  -w /workspace "${image}" python -m pytest -q \
  >"${run_root}/evidence/pytest.log" 2>&1

docker run --rm --network none --user "${uid_gid}" \
  -e PYTHONDONTWRITEBYTECODE=1 -e OPENAI_API_KEY= \
  -v "${source_root}:/workspace:ro" \
  -v "${run_root}:/evidence" \
  -v "${run_root}/dry1-cache:/workspace/.cache" \
  -w /workspace "${image}" python -m src.benchmark.validate_dataset \
  --input causal_locomo_final_with_history.jsonl \
  --report /evidence/evidence/dataset-validation.json \
  >"${run_root}/evidence/dataset-validation.log" 2>&1

run_smoke() {
  local attempt="$1"
  local cache_dir="${run_root}/${attempt}-cache"
  docker run --rm --network none --user "${uid_gid}" \
    -e PYTHONDONTWRITEBYTECODE=1 -e OPENAI_API_KEY= \
    -v "${source_root}:/workspace:ro" \
    -v "${run_root}:/evidence" \
    -v "${cache_dir}:/workspace/.cache" \
    -w /workspace "${image}" python -m src.experiments.run_experiment \
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

finished_at="$(date -Is)"
printf 'run_id\tstarted_at\tfinished_at\n%s\t%s\t%s\n' \
  "${RUN_ID}" "${started_at}" "${finished_at}" >"${run_root}/evidence/timing.tsv"
find "${run_root}" -type f ! -path "${run_root}/evidence/SHA256SUMS" -print0 \
  | sort -z | xargs -0 sha256sum >"${run_root}/evidence/SHA256SUMS"
touch "${run_root}/TERMINAL_ACCEPTED"
