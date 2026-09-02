# 实验 SOP

Status: Accepted v1, 2026-09-02.

## 0. 提出问题

每个实验先写一句可证伪问题，例如：“在不改变原始语料、query 和 token 预算时，时间感知 reranker 是否提高 conflict-aware Recall@10，同时不降低 source precision？”

然后冻结：

- baseline；
- 唯一主要改变；
- primary/guardrail metrics；
- 最小有意义改善；
- seeds 与统计方法；
- 计算、时间、费用、磁盘上限；
- 失败、重试和停止规则。

## 1. 准备数据集

1. 原始文件放在 Git 之外的只读目录，不手工覆盖或“顺便清洗”。
2. 为每个文件记录 size/SHA-256/MIME/source/license/consent 等可得元数据。
3. 用 episode 作为切分单元，防止同一人、会话、文件或时间链跨 split 泄漏。
4. 冻结 `train/dev/selection/final` 和一个全局 dataset digest。
5. `final` 在方法和阈值锁定前不可见；查看后实验进入 terminal 分析。

数据集分三类注册：

- `synthetic_public`：可进 Git 的小型 fixture，用于单测与 CI。
- `public_external`：manifest 进 Git，数字内容按许可在服务器下载并校验。
- `private_local`：只提交脱敏统计和 opaque IDs，正文与密文均不进 Git。

## 2. 冻结 experiment spec

从 `configs/experiments/memory-baseline-smoke.v1.json` 复制，使用新 `experiment_id`。spec 必须包含：

- hypothesis 与 changed factor；
- arms 及 baseline 身份；
- dataset ID/version/digest/splits；
- seeds 与配对方式；
- provider/model/prompt/extractor/index/evaluator 版本；
- primary metric、guardrail、决策规则；
- 预先限定的资源和重试上限；
- 结果目录必须全新的约束。

执行：

```bash
make check
PYTHONPATH=src python3 -m agent_enhance fingerprint configs/experiments/<spec>.json
```

将 digest 写入实验 registry 后，状态从 `draft` 改为 `frozen`。

## 3. 本机预检

- Git 工作区 clean，记录 commit/tree hash；
- schema 与单测通过；
- dataset/spec digest 与 registry 一致；
- output root 不存在；
- 最小 CPU fixture 跑通摄取→检索→回答→评测；
- 重复执行 fixture 不产生第二份规范记录。

## 4. 服务器预检

按 [服务器操作](SERVER_OPERATIONS.md) 做实时资源发现。任何 GPU 启动前必须确认：

- 包、spec、dataset 与 environment lock 的 hash 一致；
- 选定的 `/data1` 或 `/data2` 路径可写且容量达标；
- 连续三次 GPU 快照均符合门槛；
- 没有其他用户进程被纳入本项目的终止/恢复范围；
- 预估 GPU-hours、wall-hours、API 费用和 disk 未超冻结上限。

## 5. 执行

1. 为 `experiment_id/arm/seed/attempt` 分配唯一 run ID。
2. 先写 `run_record` 和 `started` event，再启动模型/GPU/API 副作用。
3. 长任务使用独立会话，记录 PID/session/GPU 物理到逻辑映射。
4. 心跳记录 step、latest artifact、GPU/CPU/RAM/disk、API cost 和日志光标。
5. 遇到 OOM、NaN、损坏输入、断联、超时、超预算或评测泄漏时按 spec fail closed。
6. 不在原 run 内临时改 batch、prompt、seed、model 或评测口径。

## 6. 完成与独立审计

正常结束时依次：

1. 封存 predictions/raw metrics/log/event/resource ledger。
2. 生成文件 size/SHA-256 inventory。
3. 用不依赖训练进程、不需 GPU 的 auditor 重算关键指标。
4. 检查 sample denominator、missing IDs、duplicate IDs、split contamination 和 source citations。
5. 所有门禁通过后才写 `completed`；否则写 `failed` 或 `unknown`。

## 7. 对比与决策

- 先按配对样本/seed 计算 treatment - baseline，再汇总。
- 同时报告点估计、置信区间、分子/分母和失败样本，不只报告最佳 seed。
- primary metric 达标但 guardrail 失败时不接受。
- selection 阶段可做预先声明的选择；final 阶段只允许一次冻结批次评测。
- 无效、资源不足或效果为零都要保留，避免发表偏差。

## 8. 快速补实验

补实验不改旧证据，而是：

1. 引用 parent experiment/run；
2. 明确补充的证据缺口；
3. 复用原 dataset digest、evaluator 和对比口径；
4. 新建 experiment ID 和全新 output root；
5. 如果方法或数据变了，评估为新实验，不与原结果冒充配对。
