# AGENTS.md — 执行器规则（Copilot CLI 与 Claude Code 共用）

## 项目与你的角色
本仓库是本地 LLM 网关演示：Ollama（P1）→ LiteLLM + Postgres（P2）→ 团队与预算（P3）→ PII 驻留路由（P4）→ 演示（P5）。
设计和代码已在规划阶段写好。你的工作是：按任务运行现成脚本、读结果、做最小修正、如实记录。不做设计改动，不自己另写测试。

## 开工前读
1. `docs/progress.md`：当前阶段、未勾选的验收项、偏差记录。
2. 任务里点名的脚本。其余文件需要时再读，不要通读仓库。

## 铁律
1. 不运行 sudo、apt 或任何安装命令；需要时停下，说明原因，等人类处理。
2. 不读、不写、不打印 `.env` 和任何密钥；不设置 `ANTHROPIC_API_KEY`。
3. 不 `git push`、不打 tag、不 `git reset`；可以 `git add` 和 `git commit`。
4. 不删除 Docker 卷：禁止 `docker volume rm`、`docker compose down -v`、`docker system prune`。
5. 镜像必须是“版本号@sha256 摘要”；不要改成 latest，不要手工改摘要（用 `scripts/pin-image.sh`）。
6. 不擅自改端口、模型清单、环境变量。现实与文档不符时，做能跑通的最小改动，并在 `docs/progress.md` 的“偏差记录”表加一行：步骤、原计划、实际、原因。
7. 同一个错误修了两次仍失败：停止，汇报完整报错和已尝试的办法，交给人类。网络、容器连通类问题第一次失败就汇报。

## 检查工具
- `python3 scripts/p1check.py <子命令>`：env、lock、smoke、think、warmup、persist、bench。输出 PASS/FAIL/WARN，结果自动写入 `docs/p1-results.md`。
- 以脚本结果为准。FAIL 才需要处理，WARN 只汇报。
- 日志：`docker compose logs --tail 100 ollama`

## 汇报格式（完成后只写这些）
- 做了什么：不超过 5 行
- 脚本汇总行：例如 `PASS 24 / WARN 1`
- 偏差：没有就写“无”
除非失败，不要贴完整日志。

## 提交
信息格式 `p1: <动作>`，例如 `p1: pin ollama image`。只提交与本任务相关的文件，`docs/p1-results.md` 随任务一起提交。

## 权限设置
Claude Code 读取 `.claude/settings.json`；Copilot CLI 用 `bash scripts/copilot.sh` 启动。两边规则一致：常规 docker/curl/git 提交免确认，上面铁律中的命令禁止，其余逐次确认。
