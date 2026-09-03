# Baseline comparison contract v1

Status: **FROZEN** on 2026-09-03 before any AgentEnhance public-benchmark result.

## Scope

The comparison corpus includes indispensable retrieval and long-context controls,
all Mem-Gallery official method families, recent 2025--2026 agent-memory systems,
the closest causal-intervention baseline, and the proposed method. Inclusion is
frozen; a method that fails reproduction remains visible with its failure state.

The primary static benchmark is Mem-Gallery (ACL 2026). WorldMemArena is the
primary lifecycle benchmark. Causal-LoCoMo and the long-video benchmarks are
secondary diagnostics. The existing SpaceNet7-derived experiments are internal
method-development evidence and cannot establish public-benchmark superiority.

## Fixed baseline table

| Group | Method | Year/venue | Modality | Selection or memory mechanism | Train | Granularity action | Counterfactual | Primary-table role | Reproduction |
|---|---|---|---|---|---|---:|---:|---|---|
| Control | No Memory | Control | None | None | No | No | No | Required | Pending |
| Control | Full Memory (Text) | Control | Captioned text | Context-limit truncation | No | No | No | Required | Pending |
| Control | Full Memory (MM) | Control | Multimodal | Context-limit truncation | No | No | No | Required | Pending |
| Control | FIFO / Recent-only | Control | Text/MM | Recency | No | No | No | Required | Pending |
| Control | BM25 | Control | Text | Lexical top-k | No | No | No | Required | Pending |
| Control | NaiveRAG | Control | Text/joint | Similarity top-k | Encoder | No | No | Required | Pending |
| Control | Hybrid BM25+Dense | Control | Text/MM | Rank fusion | Encoder | No | No | Required | Pending |
| Legacy | Generative Agents | UIST 2023 | Captioned text | Reflection memory | No | No | No | Context | Pending |
| Legacy | MemGPT | arXiv 2023 | Captioned text | Self-directed paging | No | Yes | No | Context | Pending |
| Legacy | MuRAG | EMNLP 2022 | Multimodal | Joint-embedding retrieval | Yes | No | No | Required | Pending |
| Recent | A-Mem | NeurIPS 2025 | Captioned text | Linked atomic notes | No | Yes | No | Required | Pending |
| Recent | MemoryOS | EMNLP 2025 | Captioned text | Hierarchical memory OS | No | Yes | No | Required | Pending |
| Recent | UniversalRAG | arXiv 2025 | Multimodal | Modality/granularity routing | Router | Yes | No | Required | Pending |
| Recent | Neural Graph Memory | arXiv 2025 | Multimodal | Graph traversal | Encoder | No | No | Context | Pending |
| Recent | AUGUSTUS | arXiv 2025 | Multimodal | Concept-driven hierarchy | No | Yes | No | Context | Pending |
| Recent | MIRIX | arXiv 2025 | Multimodal | Six managed memory types | No | Yes | No | Required | Pending |
| Recent | M2A | arXiv 2026 | Multimodal | Raw+semantic dual layer | No | Yes | No | Required | Pending |
| Recent | M3-Agent | ICLR 2026 | Video/audio/text | RL graph retrieval | RL | Yes | No | Secondary domain | Pending |
| Recent | MM-Mem | ACL 2026 | Video/text | Pyramidal SIB+entropy retrieval | GRPO | Yes | No | Secondary domain | Pending |
| Recent | V-Mem | arXiv 2026 | Multimodal | Modality routing+anchors | No | No | No | Required | Pending |
| Closest | CMI | arXiv 2026 | Text; MM port | No/with/perturbed intervention | No | No | Yes | Required | Pending |
| Robustness | MMA | arXiv 2026 | Multimodal | Credibility+decay+consensus | No | No | No | Secondary | Pending |
| Proposed | AgentEnhance-CEU | This work | Multimodal | Amortized DROP/COMPRESS/RETAIN | Gumbel | Yes | Yes | Required | Not started |

## Source-reported reference values

These values are immutable transcription targets, not same-protocol comparison
results. The complete long-form table, including protocol IDs, sample counts,
source commits, and eligibility flags, is stored in
`comparisons/source-reported-results.v1.csv`.

Mem-Gallery Table 4 uses Qwen2.5-VL-7B, K=10, temperature 0, and the paper's
evaluation stack over 1,711 questions.

| Method | F1 | Judge |
|---|---:|---:|
| Full Text | .3625 | .4331 |
| FIFO | .2724 | .3369 |
| NaiveRAG | .5974 | .7241 |
| Generative Agent | .3825 | .4643 |
| MemGPT | .5282 | .7306 |
| A-Mem | .6228 | .7431 |
| MemoryOS | .6109 | .7613 |
| Full Multimodal | .3354 | .4129 |
| MuRAG | .6966 | .8229 |
| UniversalRAG | .6827 | .8016 |
| NGM | .6691 | .7861 |
| AUGUSTUS | .6610 | .7797 |

V-Mem's released README reports a different GPT-4o-mini judge protocol. Its
Mem-Gallery values are Omni-SimpleMem .561, M2A .314, A-Mem .460, and V-Mem
.825; its 1,540-question non-adversarial LoCoMo values are .583, .422, .512,
and .690 respectively. The A-Mem discrepancy (.7431 versus .460) is retained
as direct evidence that source-reported values from different stacks cannot be
mixed into one ranking.

The released CMI 87-example Causal-LoCoMo run reports the following values.
The run contains 609 predictions and zero recorded failures, but its config
stores `git_commit: HEAD` and reports zero cost despite using a custom live API;
therefore the cost field is excluded from comparison.

| Method | Task score | Success | Useful F1 | Harmful reject | Poison adopt ↓ |
|---|---:|---:|---:|---:|---:|
| CMI | .8458 | .8161 | .8755 | .9902 | .0000 |
| Full history | .5147 | .2184 | .3076 | .0000 | .6207 |
| Graph memory | .8244 | .7586 | .4690 | .5500 | .5862 |
| No memory | .4293 | .0345 | .0000 | 1.0000 | .0000 |
| Reflection memory | .8449 | .7931 | .4862 | .5569 | .5402 |
| Summary memory | .7234 | .5862 | .3076 | .0000 | .6207 |
| Vector memory | .8391 | .7816 | .5011 | .5655 | .6092 |

## Fixed metric surface

The main results will cover four non-substitutable groups.

1. End task: Accuracy, QA-C, F1, EM, BLEU-1, and the frozen benchmark judge.
2. Evidence: Recall@K, Precision@K, Hit@K, MRR@K, nDCG@K, and evidence-set F1.
3. Memory reliability: write precision/recall, freshness, update handling,
   interference rejection, harmful-memory rejection, hallucination, omission,
   poisoned-memory adoption, abstention, and conformal violation.
4. Efficiency: selected evidence, prompt tokens, storage, build time, retrieval
   p50/p95, end-to-end p50/p95, cost/query, RAM, VRAM, GPU-hours, and failures.

Every metric is reported overall and, where the benchmark supports it, by
factual retrieval, visual search, test-time learning, temporal reasoning,
visual reasoning, multi-entity reasoning, knowledge resolution, conflict
detection, answer refusal, modality, evidence count, time gap, and memory-risk
condition.

## SOTA rule

`SOTA` may be used only for an audited best same-protocol value or for a
Pareto-nondominated operating point jointly considering quality and a frozen
efficiency or safety metric. Source-reported values remain in a separate
reproduction-fidelity table and can never establish superiority over a local
AgentEnhance result.

## Next gate

R0 may inspect and execute only official non-final smoke or development paths.
AgentEnhance must not be run on the public benchmarks until the baseline code,
data, evaluator, denominator, backbone, evidence budget, and failure semantics
are accepted and a separate controlled-comparison stage is frozen.

The read-only entrypoint audit is recorded in
`comparisons/r1-static-entry-audit.v1.json`. It requires denominator,
empty-answer, failure-count, and resolved-configuration guards around the
official runners; process exit zero alone is not an acceptance condition.
