# 服务器操作

Status: Accepted v1, 2026-09-02.

## 范围

关联任务中的服务器为 `10.184.17.183`，历史证据显示有 7 张可见 RTX 4090，`/data2` 在 2026-08-31 约有 1.5 TiB 可用。这些只是历史快照，不是当前可用性保证。每次实验必须现场重新查询。

## SSH 配置

密码、私钥、known_hosts 和真实用户名不进仓库。推荐在 `~/.ssh/config` 配置一个 alias：

```sshconfig
Host agent-enhance-gpu
  HostName 10.184.17.183
  User <server-user>
  IdentityFile <private-key-path>
  IdentitiesOnly yes
  StrictHostKeyChecking yes
  UserKnownHostsFile <known-hosts-path>
  ServerAliveInterval 30
  ServerAliveCountMax 6
```

首次或 host key 变化时必须由管理员核验指纹，不使用 `StrictHostKeyChecking=no`。

## 实时预检

```bash
ssh agent-enhance-gpu 'hostname; date -Is; df -h /data1 /data2; nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader; nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits'
```

选择项目目录时：

- 只能在已确认对当前用户可写的 `/data1/.../AgentEnhance` 或 `/data2/.../AgentEnhance` 下工作；
- 不猜测或复用其他项目路径；
- datasets/cache/checkpoints/runs 分开，已完成 run 只读；
- 用 `AGENT_ENHANCE_REMOTE_ROOT` 注入精确路径，不把机器私有路径提交 Git。

## 限速 SFTP

大文件上传只用 `scripts/sftp_upload_limited.sh`。脚本默认限制为 8192 Kbit/s，上传到 hash 命名的 `.partial` 路径，使用 `reput` 断点续传，远程 SHA-256 一致后才原子发布。

```bash
scripts/sftp_upload_limited.sh \
  ./bundle.tar.gz \
  agent-enhance-gpu \
  "$AGENT_ENHANCE_REMOTE_ROOT/incoming/bundle.tar.gz" \
  8192
```

传输门禁：

- 远程目标必须在 `/data1/` 或 `/data2/` 下；
- final 已存在时拒绝覆盖；
- 连接中断后重跑相同命令，`reput` 继续 `.partial` 文件；
- 本地和远程 SHA-256 不同时保留 partial 供审计，不发布；
- 小控制文件也可用 Git，但数据集、checkpoint 和大型输出不进 GitHub。

## GPU 启动门禁

1. 连续三次轮询 GPU，间隔与阈值由冻结 spec 决定。
2. 记录 physical GPU、`CUDA_VISIBLE_DEVICES` 和 logical GPU 映射。
3. 每个长任务必须有唯一 session 名、PID、精确命令、log 和 launch receipt。
4. 只能管理本项目有明确 run ID 的进程；其他用户进程始终保留。
5. 超预算、超时、OOM、NaN、日志无进度或数据损坏时写终态证据，不自动改参重试。

## 恢复

- 中断后先对照 run record、PID/session/GPU 和最后心跳，再决定是否可恢复。
- checkpoint 必须完整、hash 可校验且 spec 明确允许 resume。
- 无法确定外部 API 或文件发布结果时记为 `unknown`，等待人工结案，不盲目重放。
