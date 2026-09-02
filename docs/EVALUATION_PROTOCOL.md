# 多模态记忆评测协议

Status: Accepted v1, 2026-09-02.

## 评测单元

基本单元不是独立 query，而是一个带时序的 `episode`：

```text
events[] -> memory operations[] -> query -> expected evidence IDs -> answer constraints
```

event 可以是文本、代码、图片、音频、视频、文件或一条明确修订/删除。同一 episode 不能跨 split。

## 任务族

| 任务 | 主指标 | 必要护栏 |
| --- | --- | --- |
| 摄取保真 | byte/hash/source coverage | duplicate canonical rate = 0 |
| OCR/ASR/帧/代码派生 | CER/WER/field F1/coverage | derivative-source precision = 1 |
| 记忆提取 | fact precision/recall | third-party/question/injection false-write rate = 0 |
| 检索 | Recall@k, MRR, nDCG | source precision, latency, token budget |
| 时间/冲突/遗忘 | current-value accuracy | tombstone leakage = 0; conflict disclosure |
| 多跳与跨模态 | evidence-set exact/F1 | unsupported inference rate |
| 回答 | factuality, evidence attribution | citation validity, abstention calibration |
| 韧性 | replay/idempotency/recovery success | duplicated side effect = 0 |
| 效率 | p50/p95 latency, cost/query | peak RAM/VRAM/disk, failure rate |

## 最小正式协议

- 三个以上 seed，或对确定性系统证明多次运行完全一致。
- baseline/treatment 使用相同 episode 顺序和配对随机性。
- retrieval 与 answer 分开评测，防止生成模型掩盖检索失败。
- 确定性指标优先。LLM judge 要固定 provider/model/prompt/temperature/schema，报告 judge 失败率，并对临界与分歧样本人审。
- 报告 micro 和 macro 结果，同时按 modality、query type、time gap、conflict state、language 和 evidence count 分层。
- 任何 dropped/timeout/parser-failed 样本进入分母，除非 spec 预先定义了不可评估条件。

## 建议基线

1. `recent_only`：仅最近窗口，无长期记忆。
2. `lexical_bm25`：纯词法检索。
3. `dense_only`：单 embedding 检索。
4. `hybrid`：词法 + dense，无时间/冲突规则。
5. `production_reference`：当前个人 Harness 策略的冻结 adapter。

新方法至少与 `recent_only`、最强通用检索基线和 `production_reference` 对比。

## 数据泄漏门禁

- 文件内容相同或近似、同一会话、同一媒体派生物、同一事件的不同描述都必须同 split。
- OCR/ASR/summary 不能独立分配 split，必须跟随原 artifact。
- query 生成模型不得看 final answer；人工编辑后重新冻结生成器与数据版本。
- 使用真实私有历史时，评测工具不得把正文写入 Git、公开报告或不允许的 provider。

## 决策格式

最终决策只能是：

- `accept`：primary 达到预定改善，全部 guardrail 通过；
- `reject`：效果或护栏不达标；
- `inconclusive`：功效、证据或运行完整性不足；
- `invalid`：冻结协议被破坏。

报告必须列出失败和未知项，不允许把 `inconclusive` 表述为“趋势有效”。
