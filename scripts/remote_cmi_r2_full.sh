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
name_prefix="agentenhance-cmi-r2-full"

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
[[ ! -e "${run_root}" ]] || { echo "refusing existing run root" >&2; exit 9; }
[[ -z "$(docker ps -a --filter "name=^/${name_prefix}-" --format '{{.Names}}')" ]] || {
  echo "named container collision" >&2; exit 10;
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

container_run validate python -m src.benchmark.validate_dataset \
  --input causal_locomo_final_with_history.jsonl \
  --report /evidence/evidence/dataset-validation.json \
  >"${run_root}/evidence/dataset-validation.log" 2>&1

run_full() {
  local attempt="$1"
  container_run "${attempt}" python -m src.experiments.run_experiment \
    --config config/default.yaml \
    --dataset causal_locomo_final_with_history.jsonl \
    --max_examples 87 \
    --run_dir "/evidence/${attempt}" \
    --dry_run --skip_llm_judge --deterministic_only --no_cache \
    >"${run_root}/evidence/${attempt}.log" 2>&1
}

run_full full1
run_full full2

for attempt in full1 full2; do
  [[ "$(wc -l <"${run_root}/${attempt}/predictions.jsonl")" -eq 609 ]]
  [[ "$(wc -l <"${run_root}/${attempt}/scores.jsonl")" -eq 609 ]]
  [[ "$(wc -l <"${run_root}/${attempt}/failed_examples.jsonl")" -eq 0 ]]
done
cmp "${run_root}/full1/scores.jsonl" "${run_root}/full2/scores.jsonl"

python3 - "${run_root}" <<'PY'
import json
import math
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
expected_agents = {
    "no_memory", "full_history", "vector_memory", "summary_memory",
    "reflection_memory", "graph_memory", "cmi",
}
for attempt in ("full1", "full2"):
    scores = [json.loads(line) for line in (root / attempt / "scores.jsonl").read_text().splitlines()]
    predictions = [json.loads(line) for line in (root / attempt / "predictions.jsonl").read_text().splitlines()]
    pairs = {(row["example_id"], row["agent_name"]) for row in scores}
    examples = {row["example_id"] for row in scores}
    agents = {row["agent_name"] for row in scores}
    assert len(scores) == len(predictions) == len(pairs) == 609
    assert len(examples) == 87
    assert agents == expected_agents
    values = []
    def walk(value):
        if isinstance(value, float):
            values.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(scores)
    walk(predictions)
    assert all(math.isfinite(value) for value in values)
    assert all(float(row.get("estimated_cost_usd", row.get("cost_usd", 0.0))) == 0.0 for row in predictions)

report = json.loads((root / "evidence" / "dataset-validation.json").read_text())
assert report["num_records"] == 87
assert report["num_valid"] == 87
assert report["num_errors"] == 0
PY

[[ -z "$(docker ps -a --filter "name=^/${name_prefix}-" --format '{{.Names}}')" ]]
finished_at="$(date -Is)"
printf 'run_id\tstarted_at\tfinished_at\n%s\t%s\t%s\n' \
  "${RUN_ID}" "${started_at}" "${finished_at}" >"${run_root}/evidence/timing.tsv"
find "${run_root}" -type f ! -path "${run_root}/evidence/SHA256SUMS" -print0 \
  | sort -z | xargs -0 sha256sum >"${run_root}/evidence/SHA256SUMS"
touch "${run_root}/TERMINAL_ACCEPTED"
