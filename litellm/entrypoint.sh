#!/bin/sh
# LiteLLM 包装入口（P3）：把 Compose secrets 读成进程环境变量，再交给镜像原入口。
# 这样密钥不写在 compose 的 environment 里，docker inspect / docker compose config 看不到明文。
# 镜像以 root 运行，能读宿主机上权限 600 的密钥文件。用 /bin/sh 启动，文件不需要可执行位。
set -eu

secret() {
  f="/run/secrets/$1"
  if [ ! -r "$f" ]; then echo "entrypoint: 缺少密钥文件 $f（先运行 bash scripts/gen-secrets.sh）" >&2; exit 1; fi
  tr -d '\r\n' < "$f"
}

LITELLM_MASTER_KEY="$(secret litellm_master_key)"; export LITELLM_MASTER_KEY
LITELLM_SALT_KEY="$(secret litellm_salt_key)"; export LITELLM_SALT_KEY
DATABASE_URL="postgresql://litellm:$(secret postgres_password)@postgres:5432/litellm"; export DATABASE_URL
for v in "$LITELLM_MASTER_KEY" "$LITELLM_SALT_KEY"; do
  [ -n "$v" ] || { echo "entrypoint: Master Key 或 Salt Key 为空" >&2; exit 1; }
done

# 云端 key 可以为空：此时网关照常启动，只有 chat-cloud 调用返回认证错误
ANTHROPIC_API_KEY="$(secret anthropic_api_key)"
if [ -n "$ANTHROPIC_API_KEY" ]; then export ANTHROPIC_API_KEY; else unset ANTHROPIC_API_KEY; fi

exec /app/docker/prod_entrypoint.sh "$@"
