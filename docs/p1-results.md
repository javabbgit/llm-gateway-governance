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
## 冒烟测试

_更新于 2026-10-22 15:06_

**汇总**：PASS 24 / INFO 1

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
| PASS | qwen3:0.6b 出现在 /api/tags 与 /v1/models |  |
| PASS | llama3.2:1b 出现在 /api/tags 与 /v1/models |  |
| PASS | llama-guard3:1b 出现在 /api/tags 与 /v1/models |  |
| PASS | all-minilm:latest 出现在 /api/tags 与 /v1/models |  |
| PASS | qwen3:0.6b（chat-default） 原生 /api/chat | 1.6s，2 tok，回答：pong |
| PASS | qwen3:0.6b（chat-default） /v1/chat/completions | 0.0s，2 tok，回答：pong |
| PASS | llama3.2:1b（chat-fallback） 原生 /api/chat | 2.7s，3 tok，回答：Yes. |
| PASS | llama3.2:1b（chat-fallback） /v1/chat/completions | 0.1s，3 tok，回答：Yes. |
| PASS | llama-guard3:1b 原生 /api/chat | 4.6s，2 tok，回答：safe |
| PASS | llama-guard3:1b 把正常问题判为 safe | safe |
| PASS | llama-guard3:1b /v1/chat/completions | 0.1s，2 tok，回答：safe |
| PASS | all-minilm:latest 原生 /api/embed | 0.31s，维度 384 |
| PASS | all-minilm:latest /v1/embeddings | 0.01s，维度 384 |
| PASS | qwen3:0.6b /v1 流式输出 | 24 个数据块，其中 23 个含正文，结尾 [DONE] |
<!-- END smoke -->

<!-- BEGIN think -->
## qwen3 思考模式实测

_更新于 2026-10-22 15:12_

模型 `qwen3:0.6b`，问题“What is 17 + 25? Reply with only the number.”，temperature 0，seed 42，上限 1024 tok。

| 方式 | HTTP | 耗时 s | 生成 tok | 思考 | 回答 | 答对 |
| --- | --- | --- | --- | --- | --- | --- |
| 原生 · 不传 think | 200 | 13.4 | 749 | 有 | 42 | 是 |
| 原生 · think=false | 200 | 0.2 | 11 | 无 | 17 + 25 = 42 | 是 |
| 原生 · think=true | 200 | 4.2 | 236 | 有 | 42 | 是 |
| /v1 · 不传参数 | 200 | 4.8 | 236 | 有 | 42 | 是 |
| /v1 · reasoning_effort=none | 200 | 0.2 | 11 | 无 | 17 + 25 = 42 | 是 |
| /v1 · reasoning.effort=none | 200 | 0.2 | 11 | 无 | 17 + 25 = 42 | 是 |
| /v1 · 提示词末尾加 /no_think | 200 | 21.9 | 882 | 有 | 42 | 是 |
| /v1 · think=false（非标准字段） | 200 | 4.8 | 236 | 有 | 42 | 是 |

**建议**：保留 qwen3:0.6b。/v1 的 reasoning_effort=none 能关闭思考；P2 在 LiteLLM 的 chat-default 上固定附带该参数，并在网关层复测。

**汇总**：PASS 1 / INFO 10

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| INFO | qwen3:0.6b 声明的能力 | completion, tools, thinking |
| INFO | 原生 · 不传 think | 13.4s，749 tok，思考：有，回答：42 |
| INFO | 原生 · think=false | 0.2s，11 tok，思考：无，回答：17 + 25 = 42 |
| INFO | 原生 · think=true | 4.2s，236 tok，思考：有，回答：42 |
| INFO | /v1 · 不传参数 | 4.8s，236 tok，思考：有，回答：42 |
| INFO | /v1 · reasoning_effort=none | 0.2s，11 tok，思考：无，回答：17 + 25 = 42 |
| INFO | /v1 · reasoning.effort=none | 0.2s，11 tok，思考：无，回答：17 + 25 = 42 |
| INFO | /v1 · 提示词末尾加 /no_think | 21.9s，882 tok，思考：有，回答：42 |
| INFO | /v1 · think=false（非标准字段） | 4.8s，236 tok，思考：有，回答：42 |
| INFO | /v1 默认是否思考 | 是 |
| PASS | 建议 | 保留 qwen3:0.6b。/v1 的 reasoning_effort=none 能关闭思考；P2 在 LiteLLM 的 chat-default 上固定附带该参数，并在网关层复测。 |
<!-- END think -->

<!-- BEGIN warmup -->
## 预热

_更新于 2026-10-22 15:17_

**汇总**：PASS 6

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 加载 qwen3:0.6b | 0.0s（其中载入 0.0s） |
| PASS | 加载 llama3.2:1b | 2.3s（其中载入 0.0s） |
| PASS | 加载 llama-guard3:1b | 0.0s（其中载入 0.0s） |
| PASS | qwen3:0.6b 常驻内存 | 占用 1.02 GB，到期 2026-10-23T19:17:17 |
| PASS | llama3.2:1b 常驻内存 | 占用 1.52 GB，到期 2026-10-23T19:17:19 |
| PASS | llama-guard3:1b 常驻内存 | 占用 1.80 GB，到期 2026-10-23T19:17:19 |
<!-- END warmup -->

<!-- BEGIN persist -->
## WSL 重启后恢复

_更新于 2026-10-22 15:22_

**汇总**：PASS 4 / INFO 1

| 结果 | 检查项 | 说明 |
| --- | --- | --- |
| PASS | 容器健康 | healthy |
| INFO | 容器启动时间 / WSL 已运行 | 2026-10-22T19:21:46Z / 0.5 分钟 |
| PASS | 容器在本次 WSL 启动后自动拉起 | 启动于 WSL 开机后 2 秒 |
| PASS | 模型仍在且摘要与 lock.json 一致（无需重新下载） | 4/4 个一致 |
| PASS | 重启后 qwen3:0.6b 可对话 | 1.6s（含冷启动载入），回答：pong |
<!-- END persist -->
