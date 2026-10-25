# P5 实测结果

由 scripts/p5check.py 自动写入，各小节重跑时覆盖。演示本身的输出是英文，本文件沿用中文。

<!-- BEGIN docs -->
## README 与 ADR

_2026-10-25 16:00，PASS 10 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | README 章节齐全 | 7 个 |
| PASS | README 有 Mermaid 架构图 |  |
| PASS | README 没有过期的进度说法 |  |
| PASS | README 为英文（公开仓库） | 0 个中文字符 |
| PASS | 相对链接都指向存在的文件 | 全部有效 |
| PASS | ADR 文件 | 17 篇 |
| PASS | 每篇 ADR 都有 Context / Decision / Alternatives rejected / Consequences |  |
| PASS | ADR 覆盖总纲决策 1–36 | 全部覆盖（含作废的 18） |
| PASS | 文档里没有密钥样式的字符串 |  |
| PASS | docs/demo.md（演示讲稿与管理界面导览） |  |
<!-- END docs -->

<!-- BEGIN infra -->
## P5 演示前提

_2026-10-25 16:04，PASS 18 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | ollama 健康 | healthy |
| PASS | postgres 健康 | healthy |
| PASS | presidio-analyzer 健康 | healthy |
| PASS | litellm 健康 | healthy |
| PASS | 策略模式为 full | version 2026-10-p4，enforcement=full |
| PASS | 演示 key uw-loan-assistant | 存在 |
| PASS | 演示 key mkt-copywriter | 存在 |
| PASS | 演示 key demo-budget | 存在 |
| PASS | 演示 key demo-ratelimit | 存在 |
| PASS | scripts/demo.sh 就位 |  |
| PASS | scripts/reset.sh 就位 |  |
| PASS | scripts/demo.py 就位 |  |
| PASS | scripts/audit.py 就位 |  |
| PASS | scripts/keepalive.ps1 就位 |  |
| PASS | bash -n scripts/demo.sh |  |
| PASS | bash -n scripts/reset.sh |  |
| PASS | LiteLLM 启动时不联网下载价格表（离线演示前提） | LITELLM_LOCAL_MODEL_COST_MAP |
| PASS | 管理界面可达 | http://127.0.0.1:4000/ui/ → 200 |
| INFO | 云端场景 | 在线，场景 8 会真实调用 Haiku |
<!-- END infra -->

<!-- BEGIN audit -->
## 审计查询脚本 scripts/audit.py

_2026-10-25 16:04，PASS 6 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 表格输出 | TIME TEAM REQUESTED → SERVED ACTION RULE REASON PII SPEND |
| PASS | 汇总输出（按处置、规则、原因、团队、检测器） | Policy decisions: 88 from 2026-10-25 11:57 to 2026-10-25 13:08 spend $0.000799 |
| PASS | JSON 输出可解析 | 88 行 |
| PASS | 每行只有约定的列，pii_counts 只有“类型 → 整数” | 0 行异常 |
| PASS | 三种输出里搜不到语料中的任何 PII 原文 | 搜索 19 个值，命中 0 个 |
| PASS | 非法过滤参数被拒绝（不拼进 SQL） | audit: --since must look like 15m, 2h or 7d, got '1h;drop table x' |
| INFO | 审计表现状 | 共 88 行；按处置 {"reroute": 44, "pass": 40, "redact": 3, "block": 1} |

管理界面看不到 governance.pii_audit，这个脚本是它的命令行视图（总纲决策 11）。
<!-- END audit -->

<!-- BEGIN repeat -->
## demo.sh 连续运行 3 次

_2026-10-25 16:32，PASS 3 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 第 1 次 | PASS 9 / FAIL 0 / SKIP 0，审计 PASS，23 秒 |
| PASS | 第 2 次 | PASS 9 / FAIL 0 / SKIP 0，审计 PASS，24 秒 |
| PASS | 第 3 次 | PASS 9 / FAIL 0 / SKIP 0，审计 PASS，20 秒 |

每次运行开头自动重置（重建 demo-budget 与 demo-ratelimit），所以不用等限流窗口过去。

| 次 | 退出码 | PASS | FAIL | SKIP | 审计 | 秒 | 场景 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 9 | 0 | 0 | PASS | 23 | 1:PASS 2:PASS 3:PASS 4:PASS 5:PASS 6:PASS 7:PASS 8:PASS 9:PASS |
| 2 | 0 | 9 | 0 | 0 | PASS | 24 | 1:PASS 2:PASS 3:PASS 4:PASS 5:PASS 6:PASS 7:PASS 8:PASS 9:PASS |
| 3 | 0 | 9 | 0 | 0 | PASS | 20 | 1:PASS 2:PASS 3:PASS 4:PASS 5:PASS 6:PASS 7:PASS 8:PASS 9:PASS |
<!-- END repeat -->

<!-- BEGIN offline -->
## 离线模式（--offline 强制）

_2026-10-25 16:41，PASS 4 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 云端场景 8 被跳过 | SKIP：offline mode forced (--offline) |
| PASS | 本地场景 1–7、9 全部通过 | 全部 PASS |
| PASS | 审计轨迹 | PASS |
| PASS | 退出码 0，5 分钟内 | 退出码 0，21 秒 |

强制离线只证明跳过逻辑；断网实测用 --real。
<!-- END offline -->

<!-- BEGIN offline-real -->
## 离线模式（真实断网）

_2026-10-25 16:47，PASS 6 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 外网确实不可达 | 已断网 |
| PASS | 云端场景 8 被跳过 | SKIP：cannot reach api.anthropic.com:443 (offline) |
| PASS | 本地场景 1–7、9 全部通过 | 全部 PASS |
| PASS | 审计轨迹 | PASS |
| PASS | 退出码 0，5 分钟内 | 退出码 0，29 秒 |
| PASS | 离线是自动判定的（没有加 --offline） | cannot reach api.anthropic.com:443 (offline) |

真实断网验证完成后记得恢复网络。
<!-- END offline-real -->

<!-- BEGIN size -->
## 磁盘占用（快照瘦身前）

_2026-10-25 17:02，PASS 1 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| INFO | docker system df | TYPE TOTAL ACTIVE SIZE RECLAIMABLE |
| INFO | docker system df | Images 4 4 12.44GB 0B (0%) |
| INFO | docker system df | Containers 4 4 62.26MB 0B (0%) |
| INFO | docker system df | Local Volumes 2 2 3.563GB 0B (0%) |
| INFO | docker system df | Build Cache 0 0 0B 0B |
| INFO | 在用 ollama/ollama:0.40.8 | 8.41GB，2b8eecdb85aa |
| INFO | 在用 ghcr.io/berriai/litellm:v1.106.2 | 1.8GB，7294b90f868c |
| INFO | 可删 postgres:17 | 646MB，b8faeff77126 |
| INFO | 在用 postgres:17.11 | 646MB，b8faeff77126 |
| INFO | 在用 mcr.microsoft.com/presidio-analyzer:2.2.362 | 1.58GB，286e3fa7f3a7 |
| INFO | 卷 llm-gateway-governance_ollama-models | 3.49GB（不可删：模型） |
| INFO | 卷 llm-gateway-governance_pg-data | 73.24MB（不可删：key 与审计） |
| PASS | 可删镜像（compose 未引用或悬空） | 1 个：postgres:17 |

快照是整个发行版的文件，镜像层占大头。可删的只有上表标“可删”的镜像和构建缓存；卷绝不删。删除由人工运行 python3 scripts/p5check.py slim。
<!-- END size -->

<!-- BEGIN keepalive -->
## WSL 保活

keepalive.ps1 start 后关闭全部 Ubuntu 窗口 2 分钟：status 显示 Ubuntu-24.04 Running，Windows 侧 curl 网关返回 I am alive。
<!-- END keepalive -->
