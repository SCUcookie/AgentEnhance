# 架构决策

## D-001：独立研究仓库 — Accepted

AgentEnhance 与生产个人 Agent Harness 并列，通过 adapter 和脱敏快照联系。实验代码不直接写生产记忆 authority。

## D-002：原件为事实，派生物可重建 — Accepted

OCR、ASR、关键帧、摘要、embedding、图结构和模型判断都不得覆盖原始字节或人工标注。

## D-003：JSON 版本合同 + 零依赖控制面 — Accepted

使用 JSON Schema 作为跨语言合同。基础验证、指纹和 CI 只依赖 Python 3.9+ 标准库，避免为了验证环境而先安装大型 ML 栈。

## D-004：数据与 final 切分不可适应性使用 — Accepted

用 episode/group 切分防泄漏；selection 用于预先声明的选择，final 只在方法锁定后运行一次。

## D-005：运行证据只追加，输出目录不复用 — Accepted

失败与中断不删除。重试新建 run ID，并显式引用 parent run 和重试授权。

## D-006：大文件使用限速、可续传 SFTP — Accepted

上传到 hash 命名的 partial 路径，远程校验后原子发布。默认上限 8192 Kbit/s，可在实验或运维记录中调低，不使用无限速 `scp` 传大文件。

## D-007：服务器历史配置不是实时事实 — Accepted

可在文档中保留脱敏的 last-known 快照，但启动前必须重查磁盘、GPU、进程、驱动和环境，并把当次快照绑定到 run。
