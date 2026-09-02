# Qwen3-VL LoRA DDP smoke v1

This package verifies the smallest real multimodal training path needed before
ReVisMem Stage 0: the pinned Qwen3-VL 8B model is loaded with networking
disabled, two deterministic RGB images pass through the real vision processor,
LoRA updates only language-attention `q_proj` and `v_proj`, and two NCCL ranks
must finish with finite loss, changed parameters, synchronized adapters, and a
hashed checkpoint.

This is an execution smoke test, not a ReVisMem effectiveness experiment. The
two synthetic samples and two optimization steps cannot support a scientific
claim.

Before launch, freeze `spec.json` with the published model revision and model
inventory SHA-256, prepare a fresh output root with `prepare_run.py`, and retain
three consecutive GPU availability snapshots. Run `audit.py` independently
after training.
