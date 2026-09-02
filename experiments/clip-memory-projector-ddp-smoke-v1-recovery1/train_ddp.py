from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.distributed as dist
import torch.nn.functional as functional
from torch import nn
from torch.nn.parallel import DistributedDataParallel
from transformers import CLIPModel


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class MemoryProjector(nn.Module):
    def __init__(self, dimension: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(dimension, 128),
            nn.GELU(),
            nn.Linear(128, dimension),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.layers(value)


def flattened_parameters(module: nn.Module) -> torch.Tensor:
    return torch.cat([parameter.detach().reshape(-1) for parameter in module.parameters()])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--sequence-length", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=0.01)
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

    output = Path(args.output_root)
    model_dir = Path(args.model_dir)
    if rank == 0:
        model_sha256 = sha256_file(model_dir / "model.safetensors")
        if model_sha256 != args.expected_model_sha256:
            raise RuntimeError("base model SHA-256 mismatch")
        record_path = output / "run-record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["status"] = "running"
        write_json_atomic(record_path, record)
        with (output / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "schema_version": "run_event.v1",
                "run_id": args.run_id,
                "sequence": 3,
                "recorded_at": now(),
                "event_type": "launched",
                "payload": {"backend": "nccl", "world_size": world_size},
            }, sort_keys=True) + "\n")
    dist.barrier()

    base = CLIPModel.from_pretrained(str(model_dir), local_files_only=True).to(device)
    base.eval()
    for parameter in base.parameters():
        parameter.requires_grad_(False)

    torch.manual_seed(args.seed)
    projector = MemoryProjector(base.projection_dim).to(device)
    initial_parameters = flattened_parameters(projector).clone()
    distributed_projector = DistributedDataParallel(projector, device_ids=[local_rank], output_device=local_rank)
    optimizer = torch.optim.AdamW(distributed_projector.parameters(), lr=args.learning_rate)

    generator = torch.Generator(device=device)
    generator.manual_seed(args.seed + 1000 * rank)
    image_size = base.config.vision_config.image_size
    vocab_size = base.config.text_config.vocab_size
    pixel_values = torch.randn(args.batch_size, 3, image_size, image_size, generator=generator, device=device)
    input_ids = torch.randint(
        0,
        vocab_size - 1,
        (args.batch_size, args.sequence_length),
        generator=generator,
        device=device,
    )
    input_ids[:, -1] = vocab_size - 1
    attention_mask = torch.ones_like(input_ids)

    with torch.no_grad():
        image_features = functional.normalize(base.get_image_features(pixel_values=pixel_values), dim=-1)
        text_features = functional.normalize(
            base.get_text_features(input_ids=input_ids, attention_mask=attention_mask),
            dim=-1,
        )

    losses = []
    for _ in range(args.steps):
        optimizer.zero_grad(set_to_none=True)
        projected = functional.normalize(distributed_projector(image_features), dim=-1)
        loss = (1.0 - (projected * text_features).sum(dim=-1)).mean()
        if not torch.isfinite(loss):
            raise RuntimeError("non-finite loss")
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))

    final_parameters = flattened_parameters(projector)
    parameter_delta = float(torch.linalg.vector_norm(final_parameters - initial_parameters).cpu())
    gathered_parameters = [torch.empty_like(final_parameters) for _ in range(world_size)]
    dist.all_gather(gathered_parameters, final_parameters)
    sync_difference = max(
        float((gathered_parameters[0] - candidate).abs().max().cpu())
        for candidate in gathered_parameters[1:]
    )

    local_metrics = torch.tensor([losses[0], losses[-1], parameter_delta], dtype=torch.float64, device=device)
    gathered_metrics = [torch.empty_like(local_metrics) for _ in range(world_size)]
    dist.all_gather(gathered_metrics, local_metrics)

    rank_record = {
        "schema_version": "ddp_rank_result.v1",
        "run_id": args.run_id,
        "rank": rank,
        "local_rank": local_rank,
        "world_size": world_size,
        "hostname": socket.gethostname(),
        "device_name": torch.cuda.get_device_name(local_rank),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "nccl_available": dist.is_nccl_available(),
        "initial_loss": losses[0],
        "final_loss": losses[-1],
        "losses": losses,
        "parameter_delta_l2": parameter_delta,
        "ddp_parameter_sync_max_abs_diff": sync_difference,
        "finite": all(math.isfinite(value) for value in losses),
    }
    write_json_atomic(output / "metrics" / f"rank-{rank}.json", rank_record)
    dist.barrier()

    if rank == 0:
        checkpoint_path = output / "checkpoints" / "memory-projector.pt"
        torch.save({
            "schema_version": "memory_projector_checkpoint.v1",
            "run_id": args.run_id,
            "base_model": "openai/clip-vit-large-patch14",
            "base_model_revision": "32bd64288804d66eefd0ccbe215aa642df71cc41",
            "base_model_sha256": args.expected_model_sha256,
            "projector_state_dict": projector.state_dict(),
        }, checkpoint_path)
        checkpoint_sha256 = sha256_file(checkpoint_path)
        values = [value.cpu().tolist() for value in gathered_metrics]
        summary = {
            "schema_version": "ddp_training_summary.v1",
            "status": "completed",
            "run_id": args.run_id,
            "world_size": world_size,
            "backend": "nccl",
            "steps": args.steps,
            "per_rank_batch_size": args.batch_size,
            "mean_initial_loss": sum(value[0] for value in values) / world_size,
            "mean_final_loss": sum(value[1] for value in values) / world_size,
            "minimum_parameter_delta_l2": min(value[2] for value in values),
            "ddp_parameter_sync_max_abs_diff": sync_difference,
            "checkpoint": "checkpoints/memory-projector.pt",
            "checkpoint_sha256": checkpoint_sha256,
            "base_model_sha256": args.expected_model_sha256,
        }
        write_json_atomic(output / "metrics" / "training-summary.json", summary)
        record_path = output / "run-record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["status"] = "completed"
        write_json_atomic(record_path, record)
        with (output / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "schema_version": "run_event.v1",
                "run_id": args.run_id,
                "sequence": 4,
                "recorded_at": now(),
                "event_type": "completed",
                "payload": {"checkpoint_sha256": checkpoint_sha256},
            }, sort_keys=True) + "\n")
    dist.barrier()
    dist.destroy_process_group()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
