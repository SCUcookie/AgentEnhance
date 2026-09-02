from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
import torch.distributed as dist
from peft import LoraConfig, get_peft_model
from PIL import Image
from torch.nn.parallel import DistributedDataParallel
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def trainable_vector(model: torch.nn.Module) -> torch.Tensor:
    values = [parameter.detach().reshape(-1) for parameter in model.parameters() if parameter.requires_grad]
    if not values:
        raise RuntimeError("LoRA produced no trainable parameters")
    return torch.cat(values)


def longest_common_prefix(left: torch.Tensor, right: torch.Tensor) -> int:
    limit = min(left.numel(), right.numel())
    mismatch = torch.nonzero(left[:limit] != right[:limit], as_tuple=False)
    return limit if mismatch.numel() == 0 else int(mismatch[0].item())


def make_inputs(processor, rank: int, device: torch.device) -> tuple[dict, int, str]:
    samples = [
        ("solid-red", (255, 0, 0), "red"),
        ("solid-blue", (0, 0, 255), "blue"),
    ]
    sample_id, rgb, answer = samples[rank]
    image = Image.new("RGB", (112, 112), color=rgb)
    user = {
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": "Answer with one lowercase word: what is the solid color?"},
        ],
    }
    prompt = processor.apply_chat_template(
        [user],
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    full = processor.apply_chat_template(
        [user, {"role": "assistant", "content": [{"type": "text", "text": answer}]}],
        tokenize=True,
        add_generation_prompt=False,
        return_dict=True,
        return_tensors="pt",
    )
    prompt_length = longest_common_prefix(prompt["input_ids"][0], full["input_ids"][0])
    if prompt_length == 0 or prompt_length >= full["input_ids"].shape[1]:
        raise RuntimeError("could not isolate assistant target tokens")
    labels = full["input_ids"].clone()
    labels[:, :prompt_length] = -100
    if int((labels != -100).sum()) == 0:
        raise RuntimeError("assistant target token set is empty")
    inputs = {key: value.to(device) for key, value in full.items() if torch.is_tensor(value)}
    inputs["labels"] = labels.to(device)
    return inputs, int((labels != -100).sum()), sample_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20260902)
    args = parser.parse_args()

    dist.init_process_group(backend="nccl")
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    local_rank = int(os.environ["LOCAL_RANK"])
    if world_size != 2:
        raise RuntimeError(f"world size must be exactly two, got {world_size}")
    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    output = Path(args.output_root)
    model_dir = Path(args.model_dir)
    if rank == 0:
        manifest = json.loads((model_dir / "placement-manifest.json").read_text(encoding="utf-8"))
        inventory_sha256 = sha256_file(model_dir / "MODEL_FILES_SHA256SUMS")
        if manifest.get("revision") != args.expected_revision:
            raise RuntimeError("base model revision mismatch")
        if inventory_sha256 != args.expected_inventory_sha256:
            raise RuntimeError("base model inventory SHA-256 mismatch")
        record_path = output / "run-record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["status"] = "running"
        write_json_atomic(record_path, record)
        with (output / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "run_event.v1",
                        "run_id": args.run_id,
                        "sequence": 3,
                        "recorded_at": now(),
                        "event_type": "launched",
                        "payload": {"backend": "nccl", "world_size": world_size},
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    dist.barrier()

    processor = AutoProcessor.from_pretrained(
        str(model_dir),
        local_files_only=True,
        min_pixels=112 * 112,
        max_pixels=112 * 112,
    )
    base = Qwen3VLForConditionalGeneration.from_pretrained(
        str(model_dir),
        local_files_only=True,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    base.config.use_cache = False
    for parameter in base.parameters():
        parameter.requires_grad_(False)
    lora = get_peft_model(
        base,
        LoraConfig(
            r=4,
            lora_alpha=8,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=r"model\.language_model\.layers\.\d+\.self_attn\.(q_proj|v_proj)",
        ),
    )
    lora.gradient_checkpointing_enable()
    lora.enable_input_require_grads()
    lora.to(device)
    lora.train()
    initial = trainable_vector(lora).clone()
    trainable_count = sum(parameter.numel() for parameter in lora.parameters() if parameter.requires_grad)
    distributed = DistributedDataParallel(lora, device_ids=[local_rank], output_device=local_rank)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in distributed.parameters() if parameter.requires_grad),
        lr=args.learning_rate,
    )
    inputs, assistant_token_count, sample_id = make_inputs(processor, rank, device)
    has_pixels = "pixel_values" in inputs and inputs["pixel_values"].numel() > 0
    if not has_pixels:
        raise RuntimeError("processor emitted no image pixels")

    torch.cuda.reset_peak_memory_stats(device)
    losses: list[float] = []
    for _ in range(args.steps):
        optimizer.zero_grad(set_to_none=True)
        loss = distributed(**inputs).loss
        if not torch.isfinite(loss):
            raise RuntimeError("non-finite loss")
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))

    final = trainable_vector(lora)
    parameter_delta = float(torch.linalg.vector_norm(final - initial).cpu())
    gathered_parameters = [torch.empty_like(final) for _ in range(world_size)]
    dist.all_gather(gathered_parameters, final)
    sync_difference = max(
        float((gathered_parameters[0] - candidate).abs().max().cpu())
        for candidate in gathered_parameters[1:]
    )
    local_metrics = torch.tensor(
        [losses[0], losses[-1], parameter_delta, torch.cuda.max_memory_allocated(device)],
        dtype=torch.float64,
        device=device,
    )
    gathered_metrics = [torch.empty_like(local_metrics) for _ in range(world_size)]
    dist.all_gather(gathered_metrics, local_metrics)
    write_json_atomic(
        output / "metrics" / f"rank-{rank}.json",
        {
            "schema_version": "qwen3vl_lora_ddp_rank_result.v1",
            "run_id": args.run_id,
            "rank": rank,
            "local_rank": local_rank,
            "world_size": world_size,
            "hostname": socket.gethostname(),
            "device_name": torch.cuda.get_device_name(local_rank),
            "sample_id": sample_id,
            "assistant_token_count": assistant_token_count,
            "pixel_values_present": has_pixels,
            "trainable_parameter_count": trainable_count,
            "losses": losses,
            "initial_loss": losses[0],
            "final_loss": losses[-1],
            "parameter_delta_l2": parameter_delta,
            "ddp_parameter_sync_max_abs_diff": sync_difference,
            "peak_vram_bytes": int(torch.cuda.max_memory_allocated(device)),
            "finite": all(math.isfinite(value) for value in losses),
        },
    )
    dist.barrier()

    if rank == 0:
        adapter_dir = output / "checkpoints" / "lora-adapter"
        lora.save_pretrained(adapter_dir, safe_serialization=True)
        adapter_files = [path for path in sorted(adapter_dir.rglob("*")) if path.is_file()]
        adapter_inventory = [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in adapter_files
        ]
        values = [value.cpu().tolist() for value in gathered_metrics]
        summary = {
            "schema_version": "qwen3vl_lora_ddp_training_summary.v1",
            "status": "completed",
            "run_id": args.run_id,
            "world_size": world_size,
            "backend": "nccl",
            "steps": args.steps,
            "mean_initial_loss": sum(value[0] for value in values) / world_size,
            "mean_final_loss": sum(value[1] for value in values) / world_size,
            "minimum_parameter_delta_l2": min(value[2] for value in values),
            "maximum_peak_vram_bytes": max(int(value[3]) for value in values),
            "ddp_parameter_sync_max_abs_diff": sync_difference,
            "base_model_revision": args.expected_revision,
            "base_model_inventory_sha256": args.expected_inventory_sha256,
            "adapter_inventory": adapter_inventory,
        }
        write_json_atomic(output / "metrics" / "training-summary.json", summary)
        record_path = output / "run-record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["status"] = "completed"
        write_json_atomic(record_path, record)
        with (output / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "run_event.v1",
                        "run_id": args.run_id,
                        "sequence": 4,
                        "recorded_at": now(),
                        "event_type": "completed",
                        "payload": {"adapter_file_count": len(adapter_inventory)},
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    dist.barrier()
    dist.destroy_process_group()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
