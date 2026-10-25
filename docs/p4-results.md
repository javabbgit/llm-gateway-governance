# P4 实测结果

由 scripts/p4check.py 自动写入，各小节重跑时覆盖。表格里只有类型、数量与规则编号，不含任何 PII 原文。

<!-- BEGIN infra -->
## P4a 基础设施：Presidio 与 LiteLLM 依赖

_2026-10-25 11:30，PASS 8 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | Presidio 镜像锁定版本与摘要 | mcr.microsoft.com/presidio-analyzer:2.2.362@sha256:286e3fa7f3a7426e775e8564fe1870f1ba8f999d3ab8bbb8cc46a44355d9d6e9 |
| PASS | Presidio 健康检查 | healthy |
| PASS | Presidio 不映射宿主机端口 | 无 |
| PASS | 宿主机连不上 127.0.0.1:3000 |  |
| PASS | 策略里的实体 Presidio 都支持 | 9 种齐全（含 CA_SIN、CA_BANK_ACCOUNT、CA_POSTAL_CODE、STREET_ADDRESS） |
| PASS | LiteLLM 容器：tomllib、psycopg、httpx 可用 | 3.13.16 3.3.3 0.28.1 |
| PASS | 策略文件与 PRESIDIO_URL 已挂进 LiteLLM | True http://presidio-analyzer:3000 |
| INFO | Presidio 内存 | 749.5MiB / 23.47GiB |
| INFO | 策略模式 | enforcement=off；日志最后一行：5:24:49.162+00:00 policy_check: pass (p4-off) call_id=9a2eb0d9-b2d1-4999-93f2-0c191865760c… |
| PASS | Presidio 冷启动到健康 | 3 秒 |
<!-- END infra -->

<!-- BEGIN detect -->
## P4a 检测率（不经网关，插件同一份检测代码）

_2026-10-25 11:32，PASS 4 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | Presidio 每条都返回结果 | 24 条 |
| PASS | 英文用例检测率（实体实例） | 16/16 = 100% |
| PASS | 英文用例误报 | 0 个 |
| PASS | 语言判定（中文、俄语、法语、西语）全部正确 |  |
| INFO | 单次检测耗时 | 中位数 11 ms，最大 178 ms（第一条含预热） |

| 用例 | 语言判定 | 预期 | 检测到 | 结果 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| N01 | en | — | — | 一致 | 178 ms |
| N02 | en | — | — | 一致 | 12 ms |
| N03 | en | — | — | 一致 | 34 ms |
| N04 | en | — | — | 一致 | 11 ms |
| N05 | en | — | — | 一致 | 11 ms |
| N06 | en | — | — | 一致 | 11 ms |
| G01 | en | PERSON | PERSON:1 | 一致 | 10 ms |
| G02 | en | EMAIL_ADDRESS | EMAIL_ADDRESS:1 | 一致 | 174 ms |
| G03 | en | PHONE_NUMBER | PHONE_NUMBER:1 | 一致 | 20 ms |
| G04 | en | STREET_ADDRESS, CA_POSTAL_CODE | CA_POSTAL_CODE:1, STREET_ADDRESS:1 | 一致 | 11 ms |
| G05 | en | PERSON, EMAIL_ADDRESS, PHONE_NUMBER | EMAIL_ADDRESS:1, PERSON:1, PHONE_NUMBER:1 | 一致 | 17 ms |
| G06 | en | PERSON | PERSON:1 | 一致 | 10 ms |
| G07 | en | PERSON | PERSON:1 | 一致 | 13 ms |
| H01 | en | CA_SIN | CA_SIN:1 | 一致 | 10 ms |
| H02 | en | CA_SIN | CA_SIN:1 | 一致 | 10 ms |
| H03 | en | CREDIT_CARD | CREDIT_CARD:1 | 一致 | 12 ms |
| H04 | en | CA_BANK_ACCOUNT | CA_BANK_ACCOUNT:1 | 一致 | 14 ms |
| H05 | en | PERSON, CA_SIN | CA_SIN:1, PERSON:1 | 一致 | 11 ms |
| L01 | script | — | — | 不计（非英文） | 9 ms |
| L02 | script | — | PHONE_NUMBER:1 | 不计（非英文） | 9 ms |
| L03 | fr | — | PERSON:1 | 不计（非英文） | 10 ms |
| L04 | es | — | PERSON:2 | 不计（非英文） | 11 ms |
| L05 | en | — | — | 一致 | 10 ms |
| L06 | script | — | PERSON:1 | 不计（非英文） | 9 ms |

| 实体 | 预期 | 检出 |
| --- | --- | --- |
| CA_BANK_ACCOUNT | 1 | 1 |
| CA_POSTAL_CODE | 1 | 1 |
| CA_SIN | 3 | 3 |
| CREDIT_CARD | 1 | 1 |
| EMAIL_ADDRESS | 2 | 2 |
| PERSON | 5 | 5 |
| PHONE_NUMBER | 2 | 2 |
| STREET_ADDRESS | 1 | 1 |

漏检与误报如实保留，写进 P4 文档的检测率报告；非英文用例按决策 25 由语言判定处理，不计入检测率。
<!-- END detect -->

<!-- BEGIN unit -->
## P4b 处置矩阵单元测试（离线）

_2026-10-25 11:40，PASS 2 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 单元测试 | 25 个，全部通过 |
| PASS | 处置矩阵九格逐格测试 | test_every_cell 覆盖 R1–R9；另有 R10 阻断、故障与非英文兜底 |
<!-- END unit -->
