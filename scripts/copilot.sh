#!/usr/bin/env bash
# 以项目统一的权限启动 Copilot CLI：常规命令免确认，危险命令禁止，其余仍逐次确认。
# 与 .claude/settings.json 的规则保持一致；改一边时同步改另一边。
set -euo pipefail
cd "$(dirname "$0")/.."

allow='shell(docker compose ps:*),shell(docker compose logs:*),shell(docker compose up -d:*),shell(docker compose restart:*),shell(docker compose config:*),shell(docker compose exec ollama ollama:*),shell(docker inspect:*),shell(docker logs:*),shell(docker ps:*),shell(docker port:*),shell(docker pull:*),shell(docker image inspect:*),shell(curl:*),shell(jq:*),shell(python3 scripts/p1check.py:*),shell(python3 scripts/p2check.py:*),shell(bash scripts/pin-image.sh:*),shell(bash scripts/pull-models.sh),shell(git status:*),shell(git diff:*),shell(git log:*),shell(git add:*),shell(git commit:*)'
deny='shell(sudo:*),shell(apt:*),shell(apt-get:*),shell(git push:*),shell(git tag:*),shell(git reset:*),shell(docker volume rm:*),shell(docker compose down -v),shell(docker compose down --volumes),shell(docker system prune:*),shell(docker volume prune:*),shell(bash scripts/gen-env.sh:*),shell(cat .env:*)'

exec copilot --allow-tool="${allow}" --deny-tool="${deny}" "$@"
