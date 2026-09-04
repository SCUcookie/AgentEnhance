#!/usr/bin/env python3
"""Validate the inert model-cleanup v3 control-package prefreeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "model-cleanup-controller-control-package-prefreeze.v3.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(payload.get("status") == "FROZEN_BEFORE_INERT_PACKAGE_TRANSFER", "cleanup v3 package status drift")
    bindings = payload.get("payload", [])
    require(len(bindings) == 12, "cleanup v3 package bound payload count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file() and sha256_file(path) == binding["sha256"], f"cleanup v3 package payload drift: {path}")
    layout = payload["package_layout"]
    require(layout["payload_files"] == 13 and layout["symlinks"] == 0 and layout["python_bytecode_files"] == 0, "cleanup v3 package layout drift")
    transfer = payload["transport"]
    require(transfer == {"entrypoint": "scripts/sftp_upload_limited.sh", "rate_limit_kbit_per_second": 4096, "resumable_sha_bound_partial": True, "final_collision_allowed": False}, "cleanup v3 transport drift")
    remote = payload["remote_validation"]
    require(len(remote["commands"]) == 3, "cleanup v3 remote command count drift")
    for field in ("network_requests", "gpu_processes_started", "real_model_targets_read", "real_model_files_quarantined", "real_model_files_deleted"):
        require(remote[field] == 0, f"cleanup v3 inert boundary drift: {field}")
    require("authorizes no real cleanup preflight" in payload["authorization"], "cleanup v3 authorization boundary missing")
    print(json.dumps({"status": "PASS", "contract_sha256": sha256_file(CONTRACT), "bound_payload_files": 12, "packaged_payload_files": 13, "rate_limit_kbit_per_second": 4096, "cleanup_eligible_models": 0, "real_model_files_deleted": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
