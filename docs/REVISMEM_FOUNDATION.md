# ReVisMem foundation

Status: model identities frozen; model bytes and Stage-0 dataset pending.

## Research boundary

ReVisMem studies revisitable evidence memory for high-resolution multimodal
agents. It stores three separate layers:

1. a cheap semantic summary;
2. region embeddings with coordinates, time, and source identity;
3. an immutable pointer to the original image bytes.

The policy chooses whether to stop at a summary, retrieve/rerank regions, or
reopen a source region. The original bytes and annotations remain authority;
summaries, embeddings, crops, policy traces, and answers are rebuildable
derivatives.

## First 12-hour objective

The first bounded execution window prepares the real research foundation. It
does not attempt to produce a paper result.

- Materialize and hash the Qwen3-VL 8B reasoner, 2B multimodal embedding model,
  and 2B multimodal reranker. Keep the existing CLIP ViT-L/14 as a fixed
  similarity baseline.
- Download the official SpaceNet 7 training archive into an immutable external
  dataset store, record its size and SHA-256, and derive a deterministic small
  Stage-0 split without exposing a final split.
- Generate objective temporal/evidence questions from stable building IDs and
  monthly annotations. Derived records must retain AOI, timestamp, source image,
  label object, region coordinates, and generator version.
- If acquisition and validation finish inside the window, start one fresh
  LoRA/policy run. The run must be resumable through periodic checkpoints, but
  a resumed process is a new attempt and never overwrites the failed run.

The resource ceiling is four RTX 4090 GPUs, 48 GPU-hours, 12.5 wall-clock
hours, 200 GiB of project storage, and zero paid API usage.

## Required gates before GPU work

1. Every model resolves to the revision in
   `configs/models/revismem-foundation-models.v1.json`.
2. Every snapshot has a per-file SHA-256 inventory, loads with network access
   disabled, and is published read-only.
3. The SpaceNet archive and derived split have frozen digests. Train, dev, and
   selection use disjoint AOIs; `final` is not created in Stage 0.
4. The experiment spec changes only `evidence_access_policy`; model, question,
   token budget, and evaluator remain paired.
5. Three fresh GPU polls show the selected physical GPUs below the configured
   memory/utilization thresholds and no foreign process is touched.

## Non-claims

Model placement, offline loading, dataset preparation, or a Stage-0 training
curve cannot establish that ReVisMem improves multimodal memory. A scientific
claim requires paired baselines, multiple predeclared seeds, an untouched final
split, independent metric recomputation, and comparison at the same visual
token budget.
