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
