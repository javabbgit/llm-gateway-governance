# 进度与验收状态

- 当前阶段：**P1 模型层**（进行中）
- 阶段文档：P1 模型层 — 详细操作步骤（Claude Doc，规划对话维护）
- 实测结果：`docs/p1-results.md`（脚本自动生成）

## P1 验收

- [x] `docker compose up -d` 后健康检查通过
- [x] 每个模型用原生接口和 `/v1` 接口各调用成功一次（对话模型 `/v1/chat/completions`，向量模型 `/v1/embeddings`）
- [x] qwen3 思考模式的处理方式已实测确认
- [x] `wsl --shutdown` 后重进，容器自动恢复，模型无需重新下载
- [ ] 性能基线已记录
- [ ] 提交、打 tag `p1-models`，导出快照 `p1-models`

## 偏差记录

执行器发现现实与文档不符时在此加一行；规划对话据此回写文档。

| 日期 | 步骤 | 原计划 | 实际 | 原因 |
| --- | --- | --- | --- | --- |

## 快照

| 快照 | 日期 | 大小 | SHA256（前 16 位） |
| --- | --- | --- | --- |
| p0-baseline | 2026-10-22 | 2.48 GB | 见 C:\wsl-snapshots\p0-baseline.sha256.txt |

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
- [ ] 性能基线注明 HP Command Center 模式（`bench --power`）
- [ ] 第一个真实任务后，用 GitHub AI usage 校准月度额度估算
- [ ] 决定 gh 令牌是否换成只授权本仓库的细粒度令牌（P2 转公开前）
