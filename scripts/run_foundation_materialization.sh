#!/usr/bin/env bash
set -euo pipefail

root=/data1/2026/ldh/AgentEnhance
python_bin="$root/environments/revismem-qwen3vl-py310/bin/python"
materializer="$root/incoming/materialize_modelscope_snapshot.py"
incoming="$root/incoming/models"
store="$root/checkpoints/base-models"

[[ -x "$python_bin" ]] || { echo "missing Python environment: $python_bin" >&2; exit 66; }
[[ -f "$materializer" ]] || { echo "missing materializer: $materializer" >&2; exit 66; }
[[ "$(sha256sum "$materializer" | cut -d ' ' -f 1)" == a9af941df225e8cd179c9df12f4e931ba2bfd95212c0a1090b32c56a9c2293c1 ]] || {
  echo "materializer SHA-256 mismatch" >&2
  exit 74
}

verify_or_materialize() {
  local model_id=$1
  local revision=$2
  local slug=$3
  local final_dir="$store/$slug/rev-$revision"

  if [[ -d "$final_dir" ]]; then
    "$python_bin" - "$final_dir" "$model_id" "$revision" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root, model_id, revision = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manifest = json.loads((root / "placement-manifest.json").read_text())
if manifest["model_id"] != model_id or manifest["revision"] != revision:
    raise SystemExit("existing model identity does not match pinned identity")
subprocess.run(
    ["sha256sum", "--check", "MODEL_FILES_SHA256SUMS"],
    cwd=root,
    check=True,
)
PY
    echo "verified existing model: $model_id@$revision"
    return
  fi

  "$python_bin" "$materializer" \
    --model-id "$model_id" \
    --revision "$revision" \
    --incoming-root "$incoming" \
    --final-dir "$final_dir" \
    --max-workers 4
}

verify_or_materialize \
  Qwen/Qwen3-VL-8B-Instruct \
  5d854aab08710c16b980ec6d603d863b3821b915 \
  qwen3-vl-8b-instruct
verify_or_materialize \
  Qwen/Qwen3-VL-Embedding-2B \
  c35dddf20620fe32745cb3d01f87ba64ae316313 \
  qwen3-vl-embedding-2b
verify_or_materialize \
  Qwen/Qwen3-VL-Reranker-2B \
  5b295e981b1de77d875cdaafbc3a852420b6f3d4 \
  qwen3-vl-reranker-2b

printf '{"schema_version":"model_bundle_materialization.v1","status":"complete"}\n'
