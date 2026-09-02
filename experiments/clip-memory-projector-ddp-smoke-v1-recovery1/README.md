# CLIP memory projector 2-GPU DDP smoke v1 Recovery-1

This package verifies only the minimum execution foundation:

- immutable placement of cached openai/clip-vit-large-patch14;
- offline loading with a fixed Hugging Face revision and weight SHA-256;
- two-rank NCCL initialization through torchrun;
- DDP synchronization of a small trainable memory projection head;
- finite optimization, changed parameters, one rank-zero checkpoint, and an
  independent CPU audit.

It uses deterministic synthetic image tensors and token IDs. It does not access
personal memory, train the CLIP backbone, evaluate retrieval quality, or support
any scientific effectiveness claim.

Required server environment:

- /data1/anaconda3/envs/ACC/bin/python
- /data1/anaconda3/envs/ACC/bin/torchrun
- PyTorch 2.1.0+cu121
- Transformers 4.29.2
- two qualifying RTX 4090 GPUs selected after three fresh polls

Recovery-1 changes only the launcher from a missing venv-local torchrun binary
to the verified venv entrypoint: python -m torch.distributed.run. The original
pre-GPU launch failure remains immutable evidence.
