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

<!-- BEGIN models -->
## 模型锁定清单

_更新于 2026-10-22 14:58_

**汇总**：PASS 4

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | qwen3:0.6b | 751.63M Q4_K_M，0.52 GB，摘要 7df6b6e09427，能力 completion,tools,thinking |
| PASS | llama3.2:1b | 1.2B Q8_0，1.32 GB，摘要 baf6a787fdff，能力 completion,tools |
| PASS | llama-guard3:1b | 1.5B Q8_0，1.60 GB，摘要 494147e06bf9，能力 completion |
| PASS | all-minilm:latest | 23M F16，0.05 GB，摘要 1b226e2802db，能力 embedding |

| 模型 | 类型 | 别名 | 参数量 | 量化 | 大小 GB | 摘要（前 12 位） | 能力 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3:0.6b | chat | chat-default | 751.63M | Q4_K_M | 0.52 | 7df6b6e09427 | completion, tools, thinking |
| llama3.2:1b | chat | chat-fallback | 1.2B | Q8_0 | 1.32 | baf6a787fdff | completion, tools |
| llama-guard3:1b | guard | - | 1.5B | Q8_0 | 1.60 | 494147e06bf9 | completion |
| all-minilm:latest | embed | - | 23M | F16 | 0.05 | 1b226e2802db | embedding |
<!-- END models -->

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
