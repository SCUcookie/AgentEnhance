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


def capture(command):
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--spec-digest", required=True)
    parser.add_argument("--dataset-digest", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--physical-gpus", required=True)
    args = parser.parse_args()

    output = Path(args.output_root)
    if output.exists():
        raise SystemExit(f"fresh output root required: {output}")
    output.mkdir(parents=True)
    for name in ["environment", "logs", "metrics", "predictions", "checkpoints"]:
        (output / name).mkdir()

    software = {
        "schema_version": "software_snapshot.v1",
        "recorded_at": now(),
        "python": sys.version,
        "platform": platform.platform(),
        "pip_freeze": capture([sys.executable, "-m", "pip", "freeze"]),
    }
    hardware = {
        "schema_version": "hardware_snapshot.v1",
        "recorded_at": now(),
        "hostname": platform.node(),
        "physical_gpus": args.physical_gpus.split(","),
        "nvidia_smi": capture([
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,memory.used,utilization.gpu",
            "--format=csv,noheader",
        ]),
    }
    write_json(output / "environment" / "software.json", software)
    write_json(output / "environment" / "hardware.json", hardware)

    record = {
        "schema_version": "run_record.v1",
        "run_id": args.run_id,
        "experiment_id": "clip-memory-projector-ddp-smoke-v1",
        "arm_id": "ddp-two-gpu",
        "seed": 20260902,
        "attempt": 1,
        "parent_run_id": None,
        "status": "preflight_passed",
        "spec_digest": args.spec_digest,
        "dataset_digest": args.dataset_digest,
        "code": {"package": "clip-memory-projector-ddp-smoke-v1"},
        "environment": {
            "python_executable": sys.executable,
            "software_snapshot": "environment/software.json",
            "hardware_snapshot": "environment/hardware.json",
            "model": {
                "directory": args.model_dir,
                "model_safetensors_sha256": args.model_sha256,
            },
        },
        "paths": {
            "predictions": "predictions/",
            "raw_metrics": "metrics/training-summary.json",
            "logs": "logs/",
            "checkpoint": "checkpoints/memory-projector.pt",
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
                "model_sha256": args.model_sha256,
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
