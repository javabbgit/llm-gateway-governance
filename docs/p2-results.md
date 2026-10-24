# P2 实测结果

由 scripts/p2check.py 自动写入，各小节重跑时覆盖。

<!-- BEGIN pin-postgres -->
## 镜像锁定：postgres

- 镜像：`postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe`
- 来源：Docker Hub 官方镜像 postgres:17 当前的小版本 17.11，锁定于 2026-10-22 21:28
<!-- END pin-postgres -->

<!-- BEGIN pin-litellm -->
## 镜像锁定：litellm

- 镜像：`ghcr.io/berriai/litellm:v1.106.2@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7`
- 来源：BerriAI/litellm 的 GitHub 发布 v1.106.2（stable 通道），锁定于 2026-10-22 21:34
<!-- END pin-litellm -->

<!-- BEGIN env -->
## 环境版本

_2026-10-22 21:38，PASS 0 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| INFO | Docker | 29.9.2 |
| INFO | Compose | 5.6.1 |
| INFO | 镜像 ollama | ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2821a8f88b0485bdff198e8 |
| INFO | 镜像 postgres | postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe |
| INFO | 镜像 litellm | ghcr.io/berriai/litellm:v1.106.2@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7 |
| INFO | LiteLLM 版本 | 1.106.2 |
| INFO | Postgres 版本 | postgres (PostgreSQL) 17.11 (Debian 17.11-1.pgdg13+2) |
| INFO | Ollama 版本 | ollama version is 0.40.8 |
<!-- END env -->

<!-- BEGIN infra -->
## 基础设施

_2026-10-23 22:08，PASS 26 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | .env 权限 | 0o600 |
| PASS | .env 未纳入 git |  |
| PASS | .env 含 LITELLM_MASTER_KEY | sk-7d3… |
| PASS | .env 含 LITELLM_SALT_KEY | sk-1de… |
| PASS | .env 含 POSTGRES_PASSWORD | bd819c… |
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

<!-- BEGIN bypass -->
## 反向测试：绕过网关

_2026-10-22 22:05，PASS 7 / WARN 1 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 宿主机 127.0.0.1:11434（Ollama）连不上 | 拒绝连接 |
| PASS | 宿主机 127.0.0.1:5432（Postgres）连不上 | 拒绝连接 |
| PASS | 宿主机调用 Ollama /api/tags 失败 | URLError: <urlopen error [Errno 111] Connection refused> |
| PASS | 另一网络的容器连 ollama:11434 | gaierror |
| PASS | 另一网络的容器连 postgres:5432 | gaierror |
| PASS | 另一网络的容器连 172.19.0.2:11434 | TimeoutError |
| PASS | 另一网络的容器连 172.19.0.3:5432 | TimeoutError |
| WARN | 宿主机直连 Ollama 容器 IP 172.19.0.2:11434 | 可达：Linux 上宿主机能路由到网桥 IP；能在宿主机上执行命令的人本就等同 docker 组/root，记为已知边界 |

宿主机直连容器 IP 的 WARN 是预期结果，处理方式见总纲第 12 节“更严格的网络隔离”。
<!-- END bypass -->

<!-- BEGIN key -->
## 测试用虚拟 key

_2026-10-23 20:17，PASS 1 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 已创建测试 key | sk-rOr…，别名 p2-test，存于 .secrets/p2-test.key（不提交） |
<!-- END key -->

<!-- BEGIN route -->
## 经网关调用

_2026-10-24 11:56，PASS 8 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | /v1/models 列出 chat-default |  |
| PASS | /v1/models 列出 chat-fallback |  |
| PASS | 只暴露逻辑名，不暴露后端模型名 |  |
| PASS | chat-default 调用 | 2.2s，2 tok，后端 openai/qwen3:0.6b，组 chat-default，回答：pong |
| PASS | chat-fallback 调用 | 2.7s，3 tok，后端 openai/llama3.2:1b，组 chat-fallback，回答：Yes. |
| PASS | chat-default 思考关闭（应用不传参数） | 0.3s，11 tok，回答：17 + 25 = 42 |
| PASS | chat-default 思考关闭（应用传 reasoning_effort=high） | 0.2s，12 tok，回答：17 + 25 = 42. |
| PASS | chat-default 流式 | 17 个正文块，以 [DONE] 结尾，0.3s |
<!-- END route -->

<!-- BEGIN sdk -->
## OpenAI 官方 SDK（只改 base_url）

_2026-10-23 20:17，PASS 5 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| INFO | openai SDK 版本 | 2.33.0 |
| PASS | SDK 列出模型 | chat-default, chat-fallback, chat-github |
| PASS | SDK 调用 chat-default | 0.1s，回答：pong |
| PASS | SDK 调用 chat-fallback | 0.2s，回答：Swing. |
| PASS | SDK 流式 chat-default | 22 个正文块，0.4s，内容：Count from 1 to 5: 1, 2, 3, 4, 5. |
| PASS | SDK 请求未配置的模型被拒 | HTTP 403 |
<!-- END sdk -->

<!-- BEGIN fallback -->
## 降级测试

_2026-10-23 21:48，PASS 3 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 正常请求不降级 | 组 chat-default，降级次数 0 |
| PASS | chat-default 故障 → chat-fallback | 0.2s，降级次数 1，后端 openai/llama3.2:1b，回答：Yes. |
| PASS | 云端别名没有降级链（不会从云端落到别处，也不会从本地落到云端） | 500，litellm.InternalServerError: This is a mock exception for model=chat-github, to … |
<!-- END fallback -->

<!-- BEGIN plugin -->
## 治理插件占位

_2026-10-23 21:01，PASS 6 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 普通请求：插件在路由前记录逻辑名 | policy_check: pass (stub) call_id=5c9e530a-bf34-4a77-904a-21927f1dfd44 model=chat-default key_alias=p2-test ca… |
| PASS | 应用传 reasoning_effort=high：插件在路由前记录逻辑名 | policy_check: pass (stub) call_id=6d4da1ea-dc03-48fd-b7ea-6c0837f9c137 model=chat-default key_alias=p2-test ca… |
| PASS | 应用传 reasoning_effort=high：受控参数被丢弃 |  |
| PASS | 降级请求：插件在路由前记录逻辑名 | policy_check: pass (stub) call_id=f2d926ad-3bb5-41bf-8c75-b520a2cf8332 model=chat-default key_alias=p2-test ca… |
| PASS | 降级请求只经过插件一次 | 钩子在路由之前，降级发生在钩子之后 |
| PASS | 插件日志带 key 别名 |  |
<!-- END plugin -->

<!-- BEGIN nolog -->
## 日志不存原文

_2026-10-23 21:16，PASS 5 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 发送带标记串的请求 | 标记 CANARY-ef2…，call_id 83a2f345…，回答不含标记 |
| PASS | 费用日志已记录这次请求（证明日志在工作） | 行数 1 |
| PASS | 费用日志的 messages/response/请求体字段不含原文 | {}/{}/{} |
| PASS | 整库导出搜不到标记串 | 导出 234 KB |
| PASS | 三个容器的日志搜不到标记串 | 日志 12 KB |
<!-- END nolog -->

<!-- BEGIN cloud -->
## GitHub Models 云端别名

_2026-10-23 21:48，PASS 2 / WARN 0 / FAIL 2_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 令牌是细粒度 PAT | github… |
| FAIL | 目录中有 openai/gpt-4.1-mini | 限额档 ?，目录共 0 个模型 |
| FAIL | 经网关调用 chat-github | 500 litellm.InternalServerError: InternalServerError: OpenAIException - Empty or invalid response from LLM endpoint. Received: 'OK\r\n'. Check the reverse proxy or model server configuration.  LiteLLM: model group 'chat-github' failed with the  |
| INFO | 网关记的费用 | 0（GitHub Models 免费额度不出账单，P3 再定内部结算价） |
| PASS | 容器日志里没有令牌原文 |  |
<!-- END cloud -->

<!-- BEGIN persist -->
## 重启后恢复

_2026-10-24 11:56，PASS 5 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | ollama 健康 | healthy |
| PASS | postgres 健康 | healthy |
| PASS | litellm 健康 | healthy |
| PASS | 测试 key 仍有效 | 已用额度 0.0 |
| PASS | 重启后 chat-default 可调用 | 0.0s（含冷启动），回答：pong |
<!-- END persist -->

<!-- BEGIN secrets -->
## 密钥扫描

_2026-10-23 23:14，PASS 10 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 历史中从未提交 .env、.secrets/、*.key |  |
| PASS | 历史中没有 LITELLM_MASTER_KEY 的值 |  |
| PASS | 历史中没有 LITELLM_SALT_KEY 的值 |  |
| PASS | 历史中没有 POSTGRES_PASSWORD 的值 |  |
| PASS | 历史中没有 测试 key 的值 |  |
| PASS | 历史中没有GitHub 细粒度令牌格式的字符串 |  |
| PASS | 历史中没有GitHub 令牌格式的字符串 |  |
| PASS | 历史中没有Anthropic key格式的字符串 |  |
| PASS | 历史中没有sk- 形式的密钥格式的字符串 |  |
| PASS | .gitignore 覆盖 .env 与 .secrets/ | .env, .secrets/p2-test.key |

扫描范围：所有分支的完整历史与 .env 中的每一个密钥值。转公开后 GitHub 还会自动做 secret scanning。
<!-- END secrets -->

<!-- BEGIN restore -->
## 快照恢复验证

2026-10-24：p2-core.tar 导入为独立发行版 p2-verify，p2check persist 5/5 PASS（冷启动后 chat-default 2.1s），验证后已注销副本。
<!-- END restore -->
