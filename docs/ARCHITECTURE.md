# 架构

Status: Accepted v1, 2026-09-02.

## 定位

AgentEnhance 是研究控制面，不是新的生产记忆库。它用一套版本化合同描述数据、实验、运行和报告，把具体 memory backend、embedding provider、reranker、VLM/ASR/OCR 和 Agent Harness 隔离在 adapter 后。

```text
raw multimodal sources
        |
        v
dataset manifest + immutable hashes
        |
        v
adapter -> ingest/extract/index/retrieve/answer pipeline
        |                         |
        +---- append-only run events
        v
source-bound predictions and traces
        |
        v
versioned evaluators -> closed report -> comparison/audit
```

## Authority 边界

| 对象 | Authority | 可重建内容 |
| --- | --- | --- |
| 消息/附件 | 原始字节、来源 ID、时间、SHA-256 | 解析文本、缩略图、转码 |
| 标注 | 带 annotator/protocol/version 的冻结标注 | 聚合统计、质量分 |
| 实验 | 冻结 spec 与运行时 run record | 表格、图、排名 |
| 指标 | evaluator 对预测/标注生成的原始 metric JSON | 论文文字和可视化 |
| 环境 | commit、依赖锁、驱动/硬件快照 | 口头描述 |

projection 不得回写或覆盖 authority。如果 extractor 变更，用 `extractor_id + version + parameters_hash + source_hash` 建立新派生记录。

## 五层分解

1. **Dataset layer**：封存来源，定义 episode/event/query/expected evidence，冻结 train/dev/selection/final 切分。
2. **Pipeline layer**：通过 adapter 实现 ingest、derivative、index、retrieval、memory policy 与 answer assembly。
3. **Execution layer**：本机负责规划/审计，服务器负责重计算；每个 run 使用全新输出目录。
4. **Evaluation layer**：确定性 evaluator 优先，LLM judge 必须单独标记、版本化并抽样人审。
5. **Evidence layer**：汇总 manifest、events、predictions、metrics、resource ledger、failure record 和 hash inventory。

## 运行状态

```text
draft -> frozen -> preflight_passed -> running
                                  |-> completed
                                  |-> failed
                                  |-> cancelled
                                  |-> unknown
```

- `draft` 可修改；`frozen` 后任何实质变更必须新建 experiment ID。
- `unknown` 表示进程或外部副作用结果无法确定，不得自动重试。
- `failed` 不删除；如允许重试，新建 `attempt` 和 run ID，保留 parent run。

## 接口边界

后续实现只需遵守如下抽象边界，不把供应商写进实验逻辑：

- `CorpusAdapter`: 读取 episode/event/artifact，不改原件。
- `ExtractorAdapter`: 产生带来源的 OCR/ASR/frame/summary/embedding。
- `MemorySystemAdapter`: reset/build/update/delete/query/snapshot。
- `AgentAdapter`: 在给定 context packet 上生成回答与证据引用。
- `Evaluator`: 只读取 prediction 和 gold，输出闭合 metric record。

所有 adapter 必须通过同一 conformance suite，才能进入正式对比。

## 可快速重做的单元

一个完整 reproduction bundle 必须包含：

- 冻结 experiment spec 及 digest；
- dataset manifest 及 digest，不含私有正文；
- 代码 commit/tree hash 和 dirty diff hash（正式运行应为 clean）；
- 环境锁和硬件/驱动快照；
- 精确命令、seed、输入/输出路径和资源上限；
- predictions、raw metrics、events、终态、资源 ledger 和 SHA-256 inventory；
- 不需要网络和 GPU 的独立审计入口。
