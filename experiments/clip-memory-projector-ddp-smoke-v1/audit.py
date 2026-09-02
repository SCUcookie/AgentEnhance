from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    args = parser.parse_args()
    root = Path(args.output_root)
    failures = []

    summary = json.loads((root / "metrics" / "training-summary.json").read_text(encoding="utf-8"))
    record = json.loads((root / "run-record.json").read_text(encoding="utf-8"))
    ranks = [
        json.loads((root / "metrics" / f"rank-{rank}.json").read_text(encoding="utf-8"))
        for rank in range(2)
    ]
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if summary.get("world_size") != 2 or {item.get("rank") for item in ranks} != {0, 1}:
        failures.append("WORLD_SIZE_OR_RANK_SET_MISMATCH")
    if any(item.get("world_size") != 2 for item in ranks):
        failures.append("RANK_WORLD_SIZE_MISMATCH")
    if any(not item.get("finite") for item in ranks):
        failures.append("NON_FINITE_LOSS")
    numeric_losses = [item[key] for item in ranks for key in ["initial_loss", "final_loss"]]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric_losses):
        failures.append("INVALID_LOSS_VALUE")
    if not summary.get("mean_final_loss", math.inf) < summary.get("mean_initial_loss", -math.inf):
        failures.append("MEAN_LOSS_DID_NOT_DECREASE")
    if not summary.get("minimum_parameter_delta_l2", 0) > 0:
        failures.append("PARAMETERS_DID_NOT_CHANGE")
    if summary.get("ddp_parameter_sync_max_abs_diff", math.inf) > 1e-7:
        failures.append("DDP_PARAMETERS_NOT_SYNCHRONIZED")
    if summary.get("base_model_sha256") != args.expected_model_sha256:
        failures.append("BASE_MODEL_IDENTITY_MISMATCH")

    checkpoint = root / summary.get("checkpoint", "")
    if not checkpoint.is_file():
        failures.append("CHECKPOINT_MISSING")
    elif sha256_file(checkpoint) != summary.get("checkpoint_sha256"):
        failures.append("CHECKPOINT_SHA256_MISMATCH")
    if record.get("status") != "completed":
        failures.append("RUN_NOT_COMPLETED")
    if [item.get("sequence") for item in events] != [1, 2, 3, 4]:
        failures.append("EVENT_SEQUENCE_INVALID")

    report = {
        "schema_version": "clip_ddp_smoke_audit.v1",
        "status": "passed" if not failures else "failed",
        "run_id": summary.get("run_id"),
        "world_size": summary.get("world_size"),
        "mean_initial_loss": summary.get("mean_initial_loss"),
        "mean_final_loss": summary.get("mean_final_loss"),
        "ddp_parameter_sync_max_abs_diff": summary.get("ddp_parameter_sync_max_abs_diff"),
        "checkpoint_sha256": summary.get("checkpoint_sha256"),
        "failures": failures,
        "scientific_claim_allowed": False,
    }
    destination = root / "independent-audit.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
