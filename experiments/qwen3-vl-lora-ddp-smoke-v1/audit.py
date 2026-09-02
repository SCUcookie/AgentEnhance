from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    args = parser.parse_args()
    root = Path(args.output_root)
    failures: list[str] = []

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
    if any(not item.get("pixel_values_present") for item in ranks):
        failures.append("MULTIMODAL_INPUT_MISSING")
    if any(item.get("assistant_token_count", 0) <= 0 for item in ranks):
        failures.append("ASSISTANT_TARGET_MISSING")
    if any(item.get("trainable_parameter_count", 0) <= 0 for item in ranks):
        failures.append("TRAINABLE_PARAMETERS_MISSING")
    numeric_losses = [item[key] for item in ranks for key in ["initial_loss", "final_loss"]]
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric_losses):
        failures.append("INVALID_LOSS_VALUE")
    if summary.get("minimum_parameter_delta_l2", 0) <= 0:
        failures.append("PARAMETERS_DID_NOT_CHANGE")
    if summary.get("ddp_parameter_sync_max_abs_diff", math.inf) > 1e-6:
        failures.append("DDP_PARAMETERS_NOT_SYNCHRONIZED")
    if summary.get("base_model_revision") != args.expected_revision:
        failures.append("BASE_MODEL_REVISION_MISMATCH")
    if summary.get("base_model_inventory_sha256") != args.expected_inventory_sha256:
        failures.append("BASE_MODEL_INVENTORY_MISMATCH")
    if record.get("status") != "completed":
        failures.append("RUN_NOT_COMPLETED")
    if [event.get("sequence") for event in events] != [1, 2, 3, 4]:
        failures.append("EVENT_SEQUENCE_INVALID")

    adapter_inventory = summary.get("adapter_inventory", [])
    if not adapter_inventory:
        failures.append("ADAPTER_INVENTORY_EMPTY")
    for item in adapter_inventory:
        path = root / item.get("path", "")
        if not path.is_file():
            failures.append(f"ADAPTER_FILE_MISSING:{item.get('path')}")
        elif path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get("sha256"):
            failures.append(f"ADAPTER_FILE_IDENTITY_MISMATCH:{item.get('path')}")

    report = {
        "schema_version": "qwen3vl_lora_ddp_smoke_audit.v1",
        "status": "passed" if not failures else "failed",
        "run_id": summary.get("run_id"),
        "world_size": summary.get("world_size"),
        "mean_initial_loss": summary.get("mean_initial_loss"),
        "mean_final_loss": summary.get("mean_final_loss"),
        "ddp_parameter_sync_max_abs_diff": summary.get("ddp_parameter_sync_max_abs_diff"),
        "maximum_peak_vram_bytes": summary.get("maximum_peak_vram_bytes"),
        "failures": failures,
        "scientific_claim_allowed": False,
    }
    (root / "independent-audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
