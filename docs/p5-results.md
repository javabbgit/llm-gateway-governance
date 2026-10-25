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
