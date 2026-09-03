# Baseline comparison evidence contract v2

Status: **FROZEN** on 2026-09-03 before AgentEnhance is evaluated on a public
comparison track.

## What changed from v1

The v1 source transcription remains immutable for provenance, but official
paper and README values are removed from the paper-facing comparison surface.
They are reproduction targets only. A missing or failed local reproduction is
reported as missing or failed and is never filled with an official value.

The main table is generated only from `comparisons/reproduced-results.v1.csv`.
That file accepts audited local values under one of three frozen matched tracks:
WorldMemArena lifecycle, Mem-Gallery static multimodal, or Causal-LoCoMo safety.
The same track fixes data, sample IDs, answer backbone, evaluator, decoding,
memory budget, denominator, and failure handling for every compared method.

## Broad register, narrow numeric table

`comparisons/baseline-register.v2.csv` records controls, legacy anchors, and a
broad 2025--2026 method pool. Tier A methods already have a common-harness path;
Tier B methods need an adapter; Tier C methods cover a useful secondary domain;
Tier D methods remain literature context until a comparable adapter exists.

Being registered does not make a method numerically comparable. Only an
accepted same-track local reproduction can enter the main results. This keeps
coverage broad without creating a false ranking from mismatched backbones,
judges, splits, budgets, or failure denominators.

## Minimum gate before the proposed method

AgentEnhance remains blocked on a public track until that track contains at
least two accepted local reproductions of non-control methods published in
2025 or 2026. Controls are still mandatory, but do not satisfy this gate.

## Model-file lifecycle

Baseline model weights downloaded into a run-owned ephemeral model directory
may be deleted after the run is accepted and independently inventoried. The
repository, immutable revision, exact file list, sizes, hashes, license/access
conditions, environment, predictions, raw metrics, logs, and resolved configs
must remain. Pre-existing or shared server models are not deletion targets.

## Claim rule

“Best” or “SOTA” is allowed only for an audited same-track result, or for a
predeclared Pareto comparison that jointly exposes quality, safety, and
efficiency. A favorable category cannot hide the aggregate or other frozen
slices. Source-reported values may appear only in a labeled fidelity appendix.
