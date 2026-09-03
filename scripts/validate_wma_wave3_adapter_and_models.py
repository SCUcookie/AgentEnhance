#!/usr/bin/env python3
"""Validate Wave-3 adapter feasibility and frozen embedding acquisitions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave3-adapter-feasibility-audit.v1.json"
MANIFEST_PATH = ROOT / "comparisons" / "wma-r1-wave3-model-prefetch-manifest.v1.json"
PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave3-model-materialization-prefreeze.v1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


audit = load(AUDIT_PATH)
manifest = load(MANIFEST_PATH)
prefreeze = load(PREFREEZE_PATH)

assert audit["status"] == "TERMINAL_ACCEPTED_FOR_ADAPTER_PREFREEZE"
source_gate = ROOT / audit["source_identity_gate"]["path"]
assert audit["source_identity_gate"]["sha256"] == sha256_file(source_gate)
assert set(row["method_id"] for row in audit["methods"]) == {"memoryos", "memgas"}
assert "no lifecycle, numerical" in audit["scientific_evidence_role"]

methods = {row["method_id"]: row for row in audit["methods"]}
memoryos = methods["memoryos"]
memgas = methods["memgas"]
assert memoryos["official_defaults"]["short_term_capacity"] == 10
assert "Do not call Memoryos.get_response" in memoryos["adapter_mapping"]["retrieve"]
assert "12 ordered user/assistant pairs" in memoryos["lifecycle_minimum"]
assert memgas["official_defaults"]["embedder"] == "contriever"
assert memgas["official_defaults"]["default_mode"] == "memgas"
assert memgas["official_defaults"]["llm_max_retries"] == 3
assert "eight quickstart/__pycache__" in " ".join(memgas["observed_semantics"])
assert "preserving the same top-1 fallback" in memgas["reproducibility_overlay"]
assert all(
    re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
    for method in methods.values()
    for item in method["audited_files"]
)

assert manifest["status"] == "FROZEN_BEFORE_DOWNLOAD"
models = {row["method_id"]: row for row in manifest["models"]}
assert set(models) == set(methods)
assert models["memoryos"]["revision"] == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
assert models["memoryos"]["expected_file_count"] == len(models["memoryos"]["allow_patterns"]) == 11
assert models["memoryos"]["expected_total_bytes"] == 91578415
assert models["memgas"]["revision"] == "2bd46a25019aeea091fd42d1f0fd4801675cf699"
assert models["memgas"]["expected_file_count"] == 8
assert models["memgas"]["expected_total_bytes"] == 438708755
assert models["memgas"]["license"]["huggingface_model_card"] == "NOT_DECLARED"
assert models["memgas"]["license"]["associated_upstream_source_repository"] == "CC-BY-NC-4.0"
assert manifest["download_policy"]["transport"].endswith("4096 Kbit/s.")
for model in models.values():
    assert len(model["expected_files"]) == model["expected_file_count"]
    assert len({row["path"] for row in model["expected_files"]}) == model["expected_file_count"]
    assert sum(row["bytes"] for row in model["expected_files"]) == model["expected_total_bytes"]

assert prefreeze["status"] == "FROZEN_BEFORE_DOWNLOAD"
assert prefreeze["source_manifest"] == str(MANIFEST_PATH.relative_to(ROOT))
assert prefreeze["source_manifest_sha256"] == sha256_file(MANIFEST_PATH)
assert prefreeze["adapter_feasibility_audit"]["path"] == str(AUDIT_PATH.relative_to(ROOT))
assert prefreeze["adapter_feasibility_audit"]["sha256"] == sha256_file(AUDIT_PATH)
assert prefreeze["downloader_sha256"] == sha256_file(ROOT / prefreeze["downloader"])
assert [row["method_id"] for row in prefreeze["execution_order"]] == ["memoryos", "memgas"]
for row in prefreeze["execution_order"]:
    model = models[row["method_id"]]
    assert row["repository"] == model["repository"]
    assert row["revision"] == model["revision"]
    assert row["target"] == model["expected_local_path"]
    assert row["target"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/")
    assert row["evidence_root"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/runs/")
assert prefreeze["scheduler"]["parallel_downloads"] == 1
assert prefreeze["execution_contract"]["retry_count"] == 0

for path in (AUDIT_PATH, MANIFEST_PATH, PREFREEZE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

print(
    json.dumps(
        {
            "status": "PASS",
            "adapter_methods": sorted(methods),
            "frozen_models": sorted(row["repository"] for row in models.values()),
            "frozen_model_bytes": sum(row["expected_total_bytes"] for row in models.values()),
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
