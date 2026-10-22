# P1 实测结果

由 `scripts/p1check.py` 与 `scripts/*.sh` 自动生成，每个小节可重复运行覆盖。
实施结束后把整份文件贴回规划对话，用于把实际情况回写进 P1 文档。

<!-- BEGIN env -->
## 环境版本

_更新于 2026-10-22 14:48_

| 项目 | 值 |
| --- | --- |
| 系统 | Ubuntu 24.04.5 LTS |
| 内核 | 6.18.54.1-microsoft-standard-WSL2 |
| CPU | 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz |
| 逻辑核数 | 8 |
| Docker Engine | 29.9.2 |
| Docker Compose | 5.6.1 |
| compose 中的镜像 | ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2821a8f88b0485bdff198e8 |
| Ollama 服务版本 | 0.40.8 |
<!-- END env -->

<!-- BEGIN pin -->
## 镜像锁定

_更新于 2026-10-22 14:41_

- 镜像：`ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2821a8f88b0485bdff198e8`
- 来源：ollama/ollama 在 GitHub 的最新正式版 v0.40.8，锁定于 2026-10-22 14:41
<!-- END pin -->

<!-- BEGIN smoke -->
## 冒烟测试（仅基础设施）

_更新于 2026-10-22 14:48_

**汇总**：PASS 10 / INFO 1

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | compose 镜像已锁定版本与摘要 | ollama/ollama:0.40.8@sha256:2b8eecdb85aa6ea67c381c8ecffec04b2658496cf2821a8f88b0485bdff198e8 |
| PASS | 容器健康检查 | healthy |
| PASS | 重启策略 unless-stopped | unless-stopped |
| PASS | 运行中的容器使用 compose 锁定的镜像 |  |
| PASS | 11434 只绑定 127.0.0.1 | 127.0.0.1:11434 |
| PASS | 环境变量 OLLAMA_NO_CLOUD=1 |  |
| PASS | 环境变量 OLLAMA_MAX_LOADED_MODELS=3 |  |
| PASS | 环境变量 OLLAMA_KEEP_ALIVE=24h |  |
| INFO | 启动日志中的云功能状态 | time=2026-10-22T18:48:27.273Z level=INFO source=routes.go:2452 msg="Ollama cloud disabled: true" |
| PASS | 宿主机访问 http://127.0.0.1:11434/ | Ollama is running |
| PASS | 服务版本与锁定标签一致 | 0.40.8 |
<!-- END smoke -->
