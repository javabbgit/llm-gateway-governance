# 进度与验收状态

- 当前阶段：**P3 治理**（进行中）
- 阶段文档：P3 治理 — 详细操作步骤（Claude Doc，规划对话维护）
- 实测结果：`docs/p3-results.md`（脚本自动生成）；之前阶段见 `docs/p1-results.md`、`docs/p2-results.md`

## P1 验收

- [x] `docker compose up -d` 后健康检查通过
- [x] 每个模型用原生接口和 `/v1` 接口各调用成功一次（对话模型 `/v1/chat/completions`，向量模型 `/v1/embeddings`）
- [x] qwen3 思考模式的处理方式已实测确认
- [x] `wsl --shutdown` 后重进，容器自动恢复，模型无需重新下载
- [x] 性能基线已记录
- [x] 提交、打 tag `p1-models`，导出快照 `p1-models`

## 偏差记录

执行器发现现实与文档不符时在此加一行；规划对话据此回写文档。

| 日期 | 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- | --- |

## 快照

| 快照 | 日期 | 大小 | SHA256（前 16 位） |
| --- | --- | --- | --- |
| p0-baseline | 2026-10-22 | 2.48 GB | 见 C:\wsl-snapshots\p0-baseline.sha256.txt |
| p1-models | 2026-10-22 | 13.81 GB | 346a91c8adf854e5 |
| p2-core | 2026-10-23 | 16.27 GB | 71c859a963e4e7ed |

## P0 实测环境基线（2026-10-22）

| 组件 | 版本 / 数值 |
| --- | --- |
| 硬件 | HP，i7-1165G7（4 核 8 线程），内存 32 GB，SSD 为 RAID（Intel VMD） |
| Windows | 11 26H2，10.0.26300.9711 |
| WSL | 3.0.3.0，内核 6.18.54.1-1 |
| Ubuntu | 24.04.5 LTS（noble），用户 llm |
| WSL 资源 | 内存 23 Gi，swap 6.0 Gi，NAT，systemd |
| Docker | Engine 29.9.2（API 1.56），containerd v2.4.2，runc 1.5.2，Compose v5.6.1 |
| git / gh | 2.43.0 / 2.103.0（账号 javabbgit） |
| Claude Code | 2.1.308，Pro 订阅，默认 Haiku 5.5 |
| Copilot CLI | 1.0.102，默认 Claude Haiku 5.5 |
| Copilot 额度 | 每月 1,500 AI credits，超额关闭 |

## 从 P0 带入的待办

- [x] 写 `scripts/snapshot.ps1`（P1 已提供）
- [x] 统一两个执行器的权限规则（`.claude/settings.json` 与 `scripts/copilot.sh`）
- [x] 性能基线注明 HP Command Center 模式（`bench --power`）
- [ ] 第一个真实任务后，用 GitHub AI usage 校准月度额度估算
- [ ] 决定 gh 令牌是否换成只授权本仓库的细粒度令牌（P2 转公开前）

## P2 网关核心

验收（对应总纲第 6 节；步骤见 P2 详细操作步骤文档）

- [x] 三个服务健康检查全部通过（步骤 3）
- [x] 反向测试：宿主机直连 Ollama、Postgres 均失败（步骤 4）
- [x] OpenAI 官方 Python SDK（只改 base_url）经网关调用两个别名成功（步骤 5）
- [x] 流式输出正常；网关对 chat-default 强制关闭思考（步骤 5）
- [x] 降级测试通过（步骤 6）
- [x] 日志可见占位插件记录，且在路由之前；日志与数据库不存原文（步骤 7）
- [x] ~~chat-github 经网关调用成功（步骤 8，可选）~~ 取消：GitHub Models 已于 2026-07-30 退役
- [x] 管理界面可登录；重启后 key 仍有效（步骤 9）
- [x] 密钥扫描通过后仓库转为公开；提交、打 tag `p2-core`，导出快照 `p2-core`（步骤 10）

### P2 偏差记录

| 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 3 | pin-image.sh litellm 找 vX.Y.Z-stable 发布 | LiteLLM 标签已改为 vX.Y.Z；手工指定 v1.106.2，并把脚本改为取标为 Latest 的发布 | 上游命名变更 |
| 8 | chat-github 经 GitHub Models 零费用调用 | GitHub Models 已于 2026-07-30 退役，接口只返回 OK；删除令牌并移除 chat-github | 规划时未核实服务现状 |

## P3 治理

验收（对应总纲第 7 节；步骤见 P3 详细操作步骤文档）

- [x] 密钥改为 Compose secrets：docker inspect 与 docker compose config 都看不到明文（步骤 3）
- [ ] chat-cloud（Haiku 5.5）经网关调用成功，应用传的采样参数被丢弃（步骤 4、9）
- [ ] 费用日志不丢行：连续 N 次本地请求正好 N 行（步骤 5）
- [ ] 本地模型按内部结算价正确计费，降级按实际模型计价（步骤 5）
- [x] 团队与 key 由 governance/org.toml 创建，可重复运行（步骤 6）
- [x] underwriting 的 key 调用 chat-cloud 被拒绝（步骤 7）
- [ ] 界面管理员有独立密码；admin + Master Key 不能再登录界面，Master Key 仍能调管理 API（步骤 8）
- [ ] 预算超标后请求被阻断，错误信息清楚（步骤 9）
- [ ] 超过限流返回 429（步骤 9）
- [ ] 云端请求同样不存原文（步骤 9）
- [ ] 对账：网关记录的云端 token 与 Anthropic Console 一致（步骤 10）
- [ ] 重启后团队、key、预算、已用额度全部保留（步骤 11）
- [ ] 提交、打 tag `p3-governance`，导出快照 `p3-governance`（步骤 12）

### P3 偏差记录

| 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- |
