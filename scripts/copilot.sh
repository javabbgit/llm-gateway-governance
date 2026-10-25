#!/usr/bin/env bash
# 以项目统一的权限启动 Copilot CLI：常规命令免确认，危险命令禁止，其余仍逐次确认。
# 与 .claude/settings.json 的规则保持一致；改一边时同步改另一边。
set -euo pipefail
cd "$(dirname "$0")/.."

allow='shell(docker compose ps:*),shell(docker compose logs:*),shell(docker compose up -d:*),shell(docker compose restart:*),shell(docker compose exec ollama ollama:*),shell(docker logs:*),shell(docker ps:*),shell(docker port:*),shell(docker pull:*),shell(docker image inspect:*),shell(curl:*),shell(jq:*),shell(python3 scripts/p1check.py:*),shell(python3 scripts/p2check.py:*),shell(python3 scripts/p3check.py:*),shell(python3 scripts/p4check.py:*),shell(python3 scripts/p5check.py:*),shell(python3 scripts/audit.py:*),shell(python3 scripts/demo.py:*),shell(bash scripts/demo.sh:*),shell(bash scripts/reset.sh:*),shell(bash scripts/pin-image.sh:*),shell(bash scripts/pull-models.sh),shell(git status:*),shell(git diff:*),shell(git log:*),shell(git add:*),shell(git commit:*)'
deny='shell(python3 scripts/p4check.py mode:*),shell(python3 scripts/p5check.py slim:*),shell(docker image rm:*),shell(docker rmi:*),shell(docker builder prune:*),shell(sudo:*),shell(apt:*),shell(apt-get:*),shell(git push:*),shell(git tag:*),shell(git reset:*),shell(docker volume rm:*),shell(docker compose down -v),shell(docker compose down --volumes),shell(docker system prune:*),shell(docker volume prune:*),shell(bash scripts/gen-env.sh:*),shell(bash scripts/gen-secrets.sh:*),shell(cat .env:*),read(.env),read(.env.p2-backup),read(.secrets/p2-test.key),read(.secrets/p3-keys.json),read(.secrets/litellm_master_key),read(.secrets/litellm_salt_key),read(.secrets/postgres_password),read(.secrets/anthropic_api_key)'

exec copilot --allow-tool="${allow}" --deny-tool="${deny}" "$@"
