# 进度与验收状态

- 当前阶段：**P5 可观测与演示**（进行中）
- 阶段文档：P5 可观测与演示 — 详细操作步骤（Claude Doc，规划对话维护）
- 实测结果：`docs/p5-results.md`（脚本自动生成）；之前阶段见 `docs/p1-results.md` … `docs/p4-results.md`

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
| p3-governance | 2026-10-24 | 16.31 GB | 22178ed033726424 |
| p4c-routing | 2026-10-25 | 17.78 GB | 6e22b56b4179e9b3 |
| p4-guardrails | 2026-10-25 | 17.80 GB | d369634c0040715f |

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
- [x] chat-cloud（Haiku 5.5）经网关调用成功，应用传的采样参数被丢弃（步骤 8）
- [x] 费用日志不丢行：连续 N 次本地请求正好 N 行（步骤 6）
- [x] 本地模型按内部结算价正确计费，降级按实际模型计价（步骤 6）
- [x] 团队与 key 由 governance/org.toml 创建，可重复运行（步骤 4）
- [x] underwriting 的 key 调用 chat-cloud 被拒绝（步骤 5）
- [x] 界面管理员有独立密码；admin + Master Key 不能再登录界面，Master Key 仍能调管理 API（步骤 9）
- [x] 预算超标后请求被阻断，错误信息清楚（步骤 7）
- [x] 超过限流返回 429（步骤 7）
- [x] 云端请求同样不存原文（步骤 8）
- [x] 对账：网关记录的云端 token 与 Anthropic Console 一致（步骤 10）
- [x] 重启后团队、key、预算、已用额度全部保留（步骤 11）
- [x] 提交、打 tag `p3-governance`，导出快照 `p3-governance`（步骤 12）

### P3 偏差记录

| 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 全部 | 见 P3 文档“改正记录” | 12 条偏差，均已处理 | 详见 Claude Doc |

## P4 安全护栏

验收（对应总纲第 8 节；步骤见 P4 详细操作步骤文档）

- [x] P4a：Presidio 锁定镜像、无对外端口、健康；检测率报告已生成（`infra`、`detect`）
- [x] P4b：处置矩阵每一格都有测试用例并通过（`unit`）
- [x] P4c：改道目标不在白名单时阻断（R10），白名单结论已记录（`allowlist`）
- [x] P4c：语料逐条处置与策略一致，改道的都由本地模型回答（`route`）
- [x] P4c：审计记录都能与 LiteLLM 请求日志对上，且查不到任何原文（`audit`）
- [x] P4d：一般敏感发往云端先脱敏，非流式与流式回答都已还原，流式协议不变（`redact`、`stream`）
- [x] P4e：fail-closed 演示通过：停掉 Presidio 后发往 DeepSeek 的请求被改道，审计原因为“检测器不可用”（`failclosed`）
- [x] P4e：非英文按无法检测处理（`lang`）
- [x] P4e：云端与改道请求都不存原文（`nolog`）；重启后保持（`persist`）
- [x] 检测率报告已写入文档
- [x] 提交、打 tag `p4-guardrails`，导出快照 `p4-guardrails`（P4c 结束时另导出 `p4c-routing`）

### P4 偏差记录

| 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| P4a 步骤 1 | 锁定 PyPI 最新版 2.2.364 | 锁定 MCR 最新版 2.2.362；SIN 改用自写识别器 | MCR 镜像比 PyPI 慢，2.2.364 无镜像；2.2.362 没有自带 CaSinRecognizer |
| P4a 步骤 3 | access 全部 PASS | demo-budget 一项 FAIL（HTTP 422 Budget exceeded） | 该 key 的预算在 P3 budget 检查中已按设计用完，超预算的 key 连 /v1/models 都被拒绝；与 P4 无关 |
| P4c 步骤 2 | 审计写入直接用 DATABASE_URL | 只保留 libpq 认识的 URL 参数（修正 2） | LiteLLM 启动时给 DATABASE_URL 追加 Prisma 专用的 connection_limit、pool_timeout，psycopg 报 ProgrammingError |
| P4c 收尾 | 提交、打 tag 后再扫密钥 | 先 secrets 扫描，再提交、打 tag、推送 | secrets 会改写 docs/p3-results.md，放在 tag 之后会使快照检查失败；已撤销那次改动，文档顺序已改 |

## P5 可观测与演示

验收（对应总纲第 9 节；步骤见 P5 详细操作步骤文档）

- [ ] 审计查询脚本：表格、汇总、JSON 可用，输出里查不到原文（`p5check.py audit`）
- [ ] `demo.sh` 连续跑三次全部 PASS，每次 5 分钟内（`p5check.py repeat`，每次开头自动重置）
- [ ] 强制离线：云端场景跳过，其余全部通过（`p5check.py offline`）
- [ ] 真实断网：自动判定离线，本地场景全部通过（`p5check.py offline --real`）
- [ ] WSL 保活：关掉所有 Ubuntu 窗口 2 分钟后网关仍可调用（`keepalive.ps1`）
- [ ] 快照瘦身：可删镜像与构建缓存已清理，卷未动（`p5check.py size`、`slim`）
- [ ] 备份录像：终端 `docs/demo/demo.cast`，管理界面录屏（MP4 不提交）
- [ ] README 与 ADR 完成（`p5check.py docs`）
- [ ] 提交、打 tag `p5-release` 与 `v1.0`，导出快照 `p5-release`

### P5 偏差记录

| 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 步骤 3 | 报错原样显示 | 报错文本去掉 key 哈希、长小数取 6 位（修正 1） | 429 报错带 LiteLLM key 哈希，会进录像 |
| 步骤 4 | Presidio 健康检查每 30 秒一次 | 加 start_interval: 2s；演示重启 Presidio 后等 Docker 状态 healthy（修正 2） | 连续演示第 3 次预检读到 starting |
