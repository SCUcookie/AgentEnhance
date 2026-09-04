#!/usr/bin/env python3
"""Validate the frozen model surface for Mem-Gallery static comparisons."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-static-model-prefetch-manifest.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads(PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BEFORE_DOWNLOAD":
        raise SystemExit("Mem-Gallery model manifest is not frozen before download")
    for row in manifest["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"Mem-Gallery model dependency drift: {row['path']}")

    models = {row["model_id"]: row for row in manifest["models"]}
    expected_ids = {
        "shared-qwen3-vl-8b-answer",
        "shared-qwen3-vl-embedding-2b",
        "cross-track-gme-qwen2-vl-2b",
        "cross-track-all-minilm-l6-v2",
        "memgallery-vmem-siglip2-base-patch16-384",
    }
    if set(models) != expected_ids:
        raise SystemExit("Mem-Gallery model surface drift")
    if any(models[key]["cleanup_eligible"] for key in models):
        raise SystemExit("model manifest prematurely permits cleanup")
    if models["shared-qwen3-vl-8b-answer"]["revision"] != "5d854aab08710c16b980ec6d603d863b3821b915":
        raise SystemExit("answer-model revision drift")
    if models["shared-qwen3-vl-embedding-2b"]["revision"] != "c35dddf20620fe32745cb3d01f87ba64ae316313":
        raise SystemExit("shared embedding revision drift")
    if models["cross-track-gme-qwen2-vl-2b"]["revision"] != "9cfa6413f704a7c1cf5064d240748e10c876b286":
        raise SystemExit("GME revision drift")
    if models["cross-track-all-minilm-l6-v2"]["revision"] != "1110a243fdf4706b3f48f1d95db1a4f5529b4d41":
        raise SystemExit("MiniLM revision drift")

    siglip = models["memgallery-vmem-siglip2-base-patch16-384"]
    if siglip["revision"] != "f775b65a79762255128c981547af89addcfe0f88":
        raise SystemExit("SigLIP2 revision drift")
    if siglip["expected_file_count"] != len(siglip["expected_files"]):
        raise SystemExit("SigLIP2 file-count mismatch")
    if siglip["expected_total_bytes"] != sum(row["bytes"] for row in siglip["expected_files"]):
        raise SystemExit("SigLIP2 byte-count mismatch")
    if "successor ownership ledger" not in siglip["ownership_gate"]:
        raise SystemExit("SigLIP2 ownership gate missing")

    aggregate = manifest["aggregate"]
    if aggregate != {
        "protected_shared_models": 2,
        "reused_project_owned_candidates": 2,
        "new_project_owned_candidates": 1,
        "new_expected_files": 9,
        "new_expected_bytes": 1540625721,
        "models_downloaded_by_this_stage": 0,
    }:
        raise SystemExit("Mem-Gallery model aggregate drift")
    if manifest["current_numeric_state"] != {
        "method_runs_started": 0,
        "scores_observed": 0,
        "official_values_used": False,
    }:
        raise SystemExit("model manifest contains premature numerical state")

    print(json.dumps({
        "status": "PASS",
        "manifest_sha256": sha256_file(PATH),
        "models": len(models),
        "new_expected_files": aggregate["new_expected_files"],
        "new_expected_bytes": aggregate["new_expected_bytes"],
        "downloaded": aggregate["models_downloaded_by_this_stage"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
