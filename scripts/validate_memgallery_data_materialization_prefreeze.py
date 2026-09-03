#!/usr/bin/env python3
"""Validate the guarded Mem-Gallery dataset materialization prefreeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-data-materialization-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    if payload.get("status") != "FROZEN_AWAITING_WAVE1_RESOURCE_GATE":
        raise SystemExit("dataset materialization stage is not resource-gated")
    for item in payload["bound_inputs"]:
        if sha256_file(ROOT / item["path"]) != item["sha256"]:
            raise SystemExit(f"bound input mismatch: {item['path']}")

    manifest = json.loads(
        (ROOT / "comparisons" / "memgallery-data-prefetch-manifest.v1.json").read_text(
            encoding="utf-8"
        )
    )
    identity = payload["dataset_identity"]
    expected = manifest["expected"]
    if identity["repository"] != manifest["source"]["repository"]:
        raise SystemExit("dataset repository drift")
    if identity["revision"] != manifest["source"]["revision"]:
        raise SystemExit("dataset revision drift")
    for key in ("files", "bytes", "lfs_files", "lfs_bytes", "dialog_files", "image_files"):
        if identity[key] != expected[key]:
            raise SystemExit(f"dataset identity aggregate drift: {key}")
    if identity["questions_expected_later"] != 1711:
        raise SystemExit("static question denominator drift")

    paths = payload["paths"]
    target = Path(paths["target"])
    stage = Path(paths["stage_root"])
    evidence = Path(paths["evidence_root"])
    if target.parent != Path("/data1/2026/ldh/AgentEnhance/datasets/raw"):
        raise SystemExit("unexpected dataset target scope")
    if stage.parent != target.parent or not stage.name.startswith(target.name + ".partial-"):
        raise SystemExit("stage is not a fresh named sibling of target")
    if evidence.parent != Path("/data1/2026/ldh/AgentEnhance/runs"):
        raise SystemExit("unexpected evidence root scope")

    gate = payload["resource_gate"]
    controller = "/data1/2026/ldh/AgentEnhance/runs/wma-r1-wave1-controller-recovery2-20260904-v1"
    if gate["required_marker"] != controller + "/TERMINAL_ACCEPTED":
        raise SystemExit("required Wave1 marker drift")
    if gate["forbidden_marker"] != controller + "/TERMINAL_REJECTED":
        raise SystemExit("forbidden Wave1 marker drift")
    if gate["required_absent_tmux_prefix"] != "agentenhance-wma":
        raise SystemExit("project tmux exclusion drift")
    if gate["required_closed_ports"] != [18113, 18114, 18120, 18220, 18221, 18222]:
        raise SystemExit("project port exclusion drift")
    if gate["current_observation"]["dataset_downloaded_bytes"] != 0:
        raise SystemExit("prefreeze was created after dataset download")

    execution = payload["execution"]
    argv = execution["argv"]
    expected_pairs = {
        "--manifest": "comparisons/memgallery-data-prefetch-manifest.v1.json",
        "--target": paths["target"],
        "--stage-root": paths["stage_root"],
        "--evidence-root": paths["evidence_root"],
        "--required-marker": gate["required_marker"],
        "--forbidden-marker": gate["forbidden_marker"],
        "--tmux-prefix": gate["required_absent_tmux_prefix"],
        "--timeout-seconds": "600",
        "--minimum-free-margin-bytes": str(gate["minimum_free_margin_bytes_after_dataset_reservation"]),
    }
    if argv[:2] != [
        "/data1/anaconda3/envs/clo-infer/bin/python3.11",
        "scripts/materialize_hf_dataset_snapshot.py",
    ]:
        raise SystemExit("materializer interpreter or script drift")
    for flag, value in expected_pairs.items():
        if argv.count(flag) != 1 or argv[argv.index(flag) + 1] != value:
            raise SystemExit(f"materializer argument drift: {flag}")
    if execution["network_retry_count"] != 0 or execution["logical_requests_per_file"] != 1:
        raise SystemExit("materializer retry policy drift")
    if execution["concurrency"] != 1:
        raise SystemExit("dataset materialization concurrency drift")

    prohibited = "\n".join(payload["explicitly_prohibited"])
    for phrase in ("Wave1", "mutable branch", "Git blob", "failed partial", "model-cleanup", "SOTA"):
        if phrase not in prohibited:
            raise SystemExit(f"missing materialization prohibition: {phrase}")
    if "no memory-method lifecycle" not in payload["scientific_boundary"]:
        raise SystemExit("dataset stage improperly authorizes scientific execution")

    print(
        json.dumps(
            {
                "status": "PASS",
                "revision": identity["revision"],
                "files": identity["files"],
                "bytes": identity["bytes"],
                "network_retry_count": execution["network_retry_count"],
                "dataset_downloaded_bytes_at_freeze": 0,
                "numerical_execution_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
