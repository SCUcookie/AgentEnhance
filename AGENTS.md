# Repository guidance

默认使用中文沟通。开始实验或修改合同前依次阅读：

1. `docs/ARCHITECTURE.md`
2. `docs/SOP.md`
3. `docs/EVALUATION_PROTOCOL.md`
4. `docs/SERVER_OPERATIONS.md`
5. `docs/DECISIONS.md`

## 固定规则

- 原始字节、原始消息、人工标注和外部回执是事实；模型输出和所有派生物是带来源的 projection。
- 已冻结的 dataset manifest、experiment spec 和完成 run 只读。任何实质变更必须升版或使用新 ID。
- 一次实验只验证一个主要变量；baseline 和 treatment 使用相同数据、seed、预处理、资源上限与 evaluator。
- 选择集与最终测试集分离。查看 final 结果后不得调参或自适应重试。
- 运行时状态、失败和资源消耗必须追加记录，不覆盖旧证据。
- 不提交个人记忆正文、数据集字节、checkpoint、密钥、cookie、密码文件或机器私有路径。
- 大文件上传服务器只使用限速 SFTP，必须支持续传并在发布前校验 SHA-256；不得用无限速 `scp`。
- 不终止、抢占或修改其他用户的 GPU 进程。

## 完成门禁

- `make check` 通过。
- 新数据集具有闭合 manifest、来源/许可、split 规则和整体指纹。
- 新实验具有 baseline、唯一变量、seed、资源上限、成功阈值和失败规则。
- 发布结论前校验 run record、指标源文件、环境快照和输出 hash。
- 长任务验证中断、恢复、重复启动和非正常终态。
