# AgentEnhance

AgentEnhance 是一个面向个人 Agent 多模态记忆增强的实验与评测仓库。它不替代生产 Agent Harness，而是为记忆摄取、派生提取、检索、时间/冲突处理和有据回答提供一个可复用、可比较、可快速重做的研究控制面。

## 核心原则

- 原始字节、原始消息和人工标注是 authority；OCR、ASR、关键帧、摘要、embedding 和模型判断都是可重建 projection。
- 每个结论都绑定数据集指纹、代码 commit、闭合实验规格、运行环境和评测器版本。
- baseline 与 treatment 共用同一切分、query 集、随机种子、资源上限和评测口径；变更一个因素就新建实验。
- 失败、取消、中断和重试都是证据；不覆盖旧 output，每次重试都使用新 run ID。
- 个人数据、数据集、checkpoint 和完整 trace 不进 Git；Git 只保存代码、schema、脱敏 manifest、小型 fixture 和闭合报告。

## 仓库布局

```text
configs/       实验与服务器配置（不含密钥）
datasets/      数据集 registry 和 manifest 模板
experiments/   实验 registry；冻结 spec 按 experiment_id 归档
schemas/       版本化的 JSON Schema 合同
src/           零第三方依赖的验证与指纹 CLI
scripts/       服务器预检和限速 SFTP 传输
docs/          架构、SOP、评测协议、服务器操作和 ADR
```

## 开始

Python 3.9+ 即可执行基础控制面：

```bash
make check
PYTHONPATH=src python3 -m agent_enhance validate .
PYTHONPATH=src python3 -m agent_enhance fingerprint path/to/file-or-directory
```

启动任何真实实验前，按 [实验 SOP](docs/SOP.md) 冻结 dataset manifest 和 experiment spec。服务器使用参见 [服务器操作](docs/SERVER_OPERATIONS.md)。

## GitHub

预期 origin：`git@github.com:SCUcookie/AgentEnhance.git`。当前主机必须先恢复 GitHub SSH key 访问，才能 push。
