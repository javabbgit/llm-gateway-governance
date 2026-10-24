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

_2026-10-22 21:38，PASS 26 / WARN 0 / FAIL 0_

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

_2026-10-23 20:17，PASS 9 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | /v1/models 列出 chat-default |  |
| PASS | /v1/models 列出 chat-fallback |  |
| PASS | /v1/models 列出 chat-github |  |
| PASS | 只暴露逻辑名，不暴露后端模型名 |  |
| PASS | chat-default 调用 | 2.5s，2 tok，后端 openai/qwen3:0.6b，组 chat-default，回答：pong |
| PASS | chat-fallback 调用 | 2.8s，3 tok，后端 openai/llama3.2:1b，组 chat-fallback，回答：Yes. |
| PASS | chat-default 思考关闭（应用不传参数） | 0.3s，11 tok，回答：17 + 25 = 42 |
| PASS | chat-default 思考关闭（应用传 reasoning_effort=high） | 0.2s，12 tok，回答：17 + 25 = 42. |
| PASS | chat-default 流式 | 25 个正文块，以 [DONE] 结尾，0.5s |
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

_2026-10-23 20:53，PASS 2 / WARN 0 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 正常请求不降级 | 组 chat-default，降级次数 0 |
| PASS | chat-default 故障 → chat-fallback | 0.2s，降级次数 1，后端 openai/llama3.2:1b，回答：Yes. |
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

_2026-10-23 21:02，PASS 3 / WARN 1 / FAIL 0_

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 发送带标记串的请求 | 标记 CANARY-ab6…，call_id a4939b4f…，回答不含标记 |
| WARN | 费用日志已记录这次请求（证明日志在工作） | 行数 0 |
| PASS | 整库导出搜不到标记串 | 导出 224 KB |
| PASS | 三个容器的日志搜不到标记串 | 日志 27 KB |
<!-- END nolog -->
