# P3 实测结果

由 scripts/p3check.py 自动写入，各小节重跑时覆盖。

<!-- BEGIN secrets -->
## 密钥：Compose secrets

_2026-10-24 11:52，PASS 23 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | .secrets/ 目录权限 700 | 0o700 |
| PASS | .secrets/litellm_master_key | 0o600，sk-7d3… |
| PASS | .secrets/litellm_salt_key | 0o600，sk-1de… |
| PASS | .secrets/postgres_password | 0o600，bd819c… |
| PASS | .secrets/anthropic_api_key | 0o600，sk-ant… |
| PASS | .env 不再保存密钥 | .env 已删除 |
| PASS | litellm_salt_key 与迁移前 .env 逐字一致 |  |
| PASS | postgres_password 与迁移前 .env 逐字一致 |  |
| INFO | .env.p2-backup 仍在 | P3 验收通过后删除（步骤 11） |
| PASS | docker compose config 不含密钥明文 |  |
| PASS | docker inspect litellm 的环境变量不含密钥明文 |  |
| PASS | litellm 以 /run/secrets 挂载密钥 |  |
| PASS | docker inspect postgres 的环境变量不含密钥明文 |  |
| PASS | postgres 以 /run/secrets 挂载密钥 |  |
| PASS | 历史中从未提交 .env、.secrets/、.env 备份 |  |
| PASS | git 历史中没有 litellm_master_key 的值 |  |
| PASS | git 历史中没有 litellm_salt_key 的值 |  |
| PASS | git 历史中没有 postgres_password 的值 |  |
| PASS | git 历史中没有 anthropic_api_key 的值 |  |
| PASS | git 历史中没有GitHub 细粒度令牌格式的字符串 |  |
| PASS | git 历史中没有GitHub 令牌格式的字符串 |  |
| PASS | git 历史中没有Anthropic key格式的字符串 |  |
| PASS | git 历史中没有sk- 形式的密钥格式的字符串 |  |
| PASS | Anthropic key 没有设成 Ubuntu 全局环境变量（否则 Claude Code 改用 API 计费） |  |

密钥只以文件形式挂进容器；容器内进程环境里仍有明文，只有容器 root 可见，这是已知边界。
<!-- END secrets -->

<!-- BEGIN infra -->
## 基础设施

_2026-10-24 11:52，PASS 24 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | .secrets/litellm_master_key 存在且权限 600 | sk-7d3… |
| PASS | .secrets/litellm_salt_key 存在且权限 600 | sk-1de… |
| PASS | .secrets/postgres_password 存在且权限 600 | bd819c… |
| PASS | Master Key 以 sk- 开头 |  |
| PASS | ollama 镜像已锁定 | ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2821a8f88b0485bdff198e8 |
| PASS | postgres 镜像已锁定 | postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe |
| PASS | litellm 镜像已锁定 | ghcr.io/berriai/litellm:v1.106.2@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7 |
| PASS | ollama 健康 | healthy |
| PASS | ollama 重启策略 | unless-stopped |
| PASS | ollama 运行的是锁定镜像 | ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2… |
| PASS | ollama 不对宿主机开放端口 | 无映射 |
| PASS | postgres 健康 | healthy |
| PASS | postgres 重启策略 | unless-stopped |
| PASS | postgres 运行的是锁定镜像 | postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04… |
| PASS | postgres 不对宿主机开放端口 | 无映射 |
| PASS | litellm 健康 | healthy |
| PASS | litellm 重启策略 | unless-stopped |
| PASS | litellm 运行的是锁定镜像 | ghcr.io/berriai/litellm:v1.106.2@sha256:7294b90f868c5c38c99b83021c7ba4… |
| PASS | litellm 端口只绑定 127.0.0.1:4000 | 127.0.0.1:4000 |
| PASS | 网关存活 | 200 |
| PASS | 网关已连上 Postgres | connected |
| PASS | 治理插件已加载 | GovernancePlugin |
| PASS | 不带 key 调用被拒 | 401 |
| PASS | 管理界面页面可访问 | http://127.0.0.1:4000/ui/ → 200 |
<!-- END infra -->

<!-- BEGIN infra-p3 -->
## 基础设施（P3 增项）

_2026-10-24 11:52，PASS 4 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | LiteLLM 用包装入口读取 secrets | ["/bin/sh","/app/config/entrypoint.sh"] |
| PASS | /v1/models 含 chat-cloud | chat-default, chat-fallback, chat-cloud |
| PASS | Anthropic key 已配置 |  |
| PASS | 入口脚本没有报缺少密钥 |  |
<!-- END infra-p3 -->

<!-- BEGIN org -->
## 组织：团队与 key

_2026-10-24 12:04，PASS 8 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 更新团队 underwriting | 模型 chat-default,chat-fallback；预算 $2.0/30d；60 RPM |
| PASS |   更新 key uw-loan-assistant | sk-lax… |
| PASS | 更新团队 marketing | 模型 chat-default,chat-fallback,chat-cloud；预算 $2.0/30d；60 RPM |
| PASS |   更新 key mkt-copywriter | sk-AH0… |
| PASS | 更新团队 it-ops | 模型 chat-default,chat-fallback,chat-cloud；预算 $0.5/30d；30 RPM |
| PASS |   更新 key ops-runbook-bot | sk-c2g… |
| PASS |   更新 key demo-budget | sk-uMi… |
| PASS |   更新 key demo-ratelimit | sk-P3U… |
<!-- END org -->

<!-- BEGIN access -->
## 团队模型白名单

_2026-10-24 12:34，PASS 8 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | uw-loan-assistant（underwriting）只看到本团队模型 | chat-default, chat-fallback |
| PASS | mkt-copywriter（marketing）只看到本团队模型 | chat-cloud, chat-default, chat-fallback |
| PASS | ops-runbook-bot（it-ops）只看到本团队模型 | chat-cloud, chat-default, chat-fallback |
| PASS | demo-budget（it-ops）只看到本团队模型 | chat-cloud, chat-default, chat-fallback |
| PASS | demo-ratelimit（it-ops）只看到本团队模型 | chat-cloud, chat-default, chat-fallback |
| PASS | 审批团队调用本地 chat-default | 200 pong |
| PASS | 审批团队调用云端 chat-cloud 被拒 | HTTP 403：The requested model 'chat-cloud' is not available for this API key, or the model name is invalid. Check the models avail… |
| PASS | 市场团队调用云端 chat-cloud | 200 Ping |

纵深防御的静态层：只有白名单挡不住把客户资料粘进市场团队的请求，那由 P4 的动态 PII 检测负责。
<!-- END access -->

<!-- BEGIN pricing -->
## 内部结算价与费用日志

_2026-10-24 12:44，PASS 6 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 连续 12 次请求，费用日志正好 12 行 | 实际 12 行 |
| PASS | 费用日志主键唯一（chatcmpl-<litellm_call_id>） | chatcmpl-3dbf87dc-996a-4541-8312-4f099d862dfb, chatcmpl-2c26c167-34bc-4ca2-87c3-029d890ff3… |
| PASS | 每行费用 = 输入 × $0.10/1M + 输出 × $0.40/1M | 12 行合计 $0.00025200 |
| PASS | key 已用额度增加量 = 费用日志合计 | 0.00000600 → 0.00025800（+0.00025200） |
| PASS | 降级后按实际模型（llama3.2）的单价计费 | model=openai/llama3.2:1b，1.075e-05，应为 1.075e-05 |
| PASS | 按团队的日汇总有数据（管理界面 Usage 页的数据源） | 5 行；汇总有延迟时隔几分钟重跑 |

内部结算价按“每 CPU 小时 $0.10”与 P1 实测吞吐折算，见 config.yaml 注释。
<!-- END pricing -->

<!-- BEGIN budget -->
## 预算超标阻断

_2026-10-24 12:57，PASS 4 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 重建 demo-budget | sk-Msc…，预算 $0.0002 |
| PASS | 超出预算后请求被阻断 | 放行 3 次后阻断，HTTP 422 |
| PASS | 错误信息清楚 | Budget has been exceeded! Key=demo-budget (sk-...YFdQ) Current cost: 0.00021749999999999997, Max budget: 0.0002 |
| PASS | 超支不超过一次调用的费用 | 已用 $0.000000，预算 $0.0002，每次约 $0.000000 |
<!-- END budget -->

<!-- BEGIN ratelimit -->
## 限流 429

_2026-10-24 12:58，PASS 1 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 每分钟 5 次：前 5 次放行，第 6 次返回 429 | 200 200 200 200 200 429 429 |
| INFO | 429 的提示 | Rate limit exceeded for api_key: 6f8b027cd9dbab98ec0bcccc01cfd42e66213f65b494a26b1af3c6436eeef85b. Limit type: requests. Current limit: 5, Remaining: 0. Limit r… |

按请求数限流：CPU 推理太慢，按 token 限流难以在演示时间内触发。
<!-- END ratelimit -->
