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

<!-- BEGIN audit-init -->
## 审计表

_2026-10-25 11:42，PASS 3 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 执行 governance/audit.sql | CREATE SCHEMA CREATE TABLE CREATE INDEX COMMENT |
| PASS | governance.pii_audit 可查询 | 0 行 |
| PASS | 约束拒绝把文本写进 pii_counts | BEGIN ERROR: new row for relation "pii_audit" violates check constraint "pii_counts_types_… |
<!-- END audit-init -->

<!-- BEGIN mode -->
## 策略模式切换

_2026-10-25 11:57，PASS 5 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | policy.toml | enforcement = "route"（未变） |
| PASS | docker compose restart litellm | Container llm-gateway-governance-litellm-1 Restarting Container llm-gateway-gove… |
| PASS | 网关恢复 | 12 秒 |
| PASS | 插件以新模式运行 | 5:57:43.683+00:00 policy_check: pass (p4-route) call_id=80bc3be2-5264-4565-ad14-58386359480e model=c… |
| PASS | 审计写入可用（刚才的请求已写进审计表） | outcome=success |

记得把 policy.toml 的这次改动和本小节一起提交：模式切换本身是需要审计的策略变更。
<!-- END mode -->

<!-- BEGIN allowlist -->
## P4c 最先验证：白名单与改道

_2026-10-25 11:58，PASS 8 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 策略模式 | enforcement=route |
| PASS | 静态层：审批团队调用 chat-deepseek 被 LiteLLM 拒绝 | HTTP 403：The requested model 'chat-deepseek' is not available for this API key, or the model name i… |
| PASS | 市场团队无 PII → chat-deepseek 放行（模拟部署回答） | 200 {'action': 'pass', 'rule': 'R7', 'level': 'none', 'reason': 'none', 'routed-model': 'chat-deepseek', 'pii': '-'} |
| PASS | 市场团队含 SIN → 改道到 chat-default（R9） | 200 rule=R9 pii=CA_SIN:1 |
| PASS | 费用日志里实际模型是本地 | model_group=chat-default |
| PASS | 只有云端模型的 key 含 SIN → 无处改道，阻断（R10） | HTTP 403：policy_blocked: rule R10 — 改道目标 chat-default 不在调用方的模型白名单里. Request contains data that may not be sen… |
| PASS | 同一个 key 无 PII 照常放行 | 200 |
| PASS | 阻断写进审计表 | block/R10/blocked |

结论：LiteLLM 只在鉴权时查一次模型白名单（源码 auth_checks.can_key_call_model），钩子里改写目标模型不会再查；所以插件在改道前自己核对 key 与团队白名单，目标不在白名单就按 R10 阻断。白名单配置因此不用为改道放宽：每个能用云端或 DeepSeek 的团队本来就有 chat-default。 阻断请求的 call_id：cef3f3fe-a81f-43a8-8de3-b18b2015c9e1
<!-- END allowlist -->
