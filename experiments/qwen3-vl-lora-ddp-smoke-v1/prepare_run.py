from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture(command: list[str]) -> dict:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--spec-digest", required=True)
    parser.add_argument("--dataset-digest", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--model-inventory-sha256", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--physical-gpus", required=True)
    args = parser.parse_args()

    output = Path(args.output_root)
    if output.exists():
        raise SystemExit(f"fresh output root required: {output}")
    output.mkdir(parents=True)
    for name in ["environment", "logs", "metrics", "checkpoints"]:
        (output / name).mkdir()

    write_json(
        output / "environment" / "software.json",
        {
            "schema_version": "software_snapshot.v1",
            "recorded_at": now(),
            "python": sys.version,
            "platform": platform.platform(),
            "pip_freeze": capture([sys.executable, "-m", "pip", "freeze"]),
        },
    )
    write_json(
        output / "environment" / "hardware.json",
        {
            "schema_version": "hardware_snapshot.v1",
            "recorded_at": now(),
            "hostname": platform.node(),
            "physical_gpus": args.physical_gpus.split(","),
            "nvidia_smi": capture(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,uuid,memory.total,memory.used,utilization.gpu",
                    "--format=csv,noheader",
                ]
            ),
        },
    )
    record = {
        "schema_version": "run_record.v1",
        "run_id": args.run_id,
        "experiment_id": "qwen3-vl-lora-ddp-smoke-v1",
        "arm_id": "lora-ddp-two-gpu",
        "seed": 20260902,
        "attempt": 1,
        "parent_run_id": None,
        "status": "preflight_passed",
        "spec_digest": args.spec_digest,
        "dataset_digest": args.dataset_digest,
        "code": {"package": "qwen3-vl-lora-ddp-smoke-v1"},
        "environment": {
            "python_executable": sys.executable,
            "software_snapshot": "environment/software.json",
            "hardware_snapshot": "environment/hardware.json",
            "model": {
                "directory": args.model_dir,
                "revision": args.model_revision,
                "inventory_sha256": args.model_inventory_sha256,
            },
        },
        "paths": {
            "raw_metrics": "metrics/training-summary.json",
            "logs": "logs/",
            "checkpoint": "checkpoints/lora-adapter/",
            "inventory": "SHA256SUMS",
        },
        "events_path": "events.jsonl",
        "terminal_reason": None,
        "output_inventory_sha256": None,
    }
    write_json(output / "run-record.json", record)
    events = [
        {
            "schema_version": "run_event.v1",
            "run_id": args.run_id,
            "sequence": 1,
            "recorded_at": now(),
            "event_type": "planned",
            "payload": {"fresh_output_root": True},
        },
        {
            "schema_version": "run_event.v1",
            "run_id": args.run_id,
            "sequence": 2,
            "recorded_at": now(),
            "event_type": "preflight_passed",
            "payload": {
                "physical_gpus": args.physical_gpus.split(","),
                "world_size": 2,
                "model_inventory_sha256": args.model_inventory_sha256,
            },
        },
    ]
    with (output / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    print(json.dumps({"status": "prepared", "run_id": args.run_id, "output_root": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
