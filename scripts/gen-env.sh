#!/usr/bin/env bash
# 生成或补全 .env：只添加缺少的变量，已有的值一律不动。
# LITELLM_SALT_KEY 一旦生成就永不更改：它加密数据库里的凭据，换了就再也解不开。
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
touch .env
chmod 600 .env

rand() { python3 -c "import secrets; print(secrets.token_hex(24))"; }
has() { grep -qE "^$1=" .env; }
added=()

add() {  # add 名字 值 注释
  if has "$1"; then echo "保留 $1（已存在，不改）"; else
    printf '\n# %s\n%s=%s\n' "$3" "$1" "$2" >> .env; added+=("$1"); fi
}

add LITELLM_MASTER_KEY "sk-$(rand)" "网关管理员密钥，以 sk- 开头。可以轮换：改这里后 docker compose up -d litellm"
add LITELLM_SALT_KEY   "sk-$(rand)" "加密数据库内凭据用。生成后永不更改，另存一份到密码管理器"
add POSTGRES_PASSWORD  "$(rand)"    "Postgres 密码（只含十六进制字符，可直接放进连接串）"
add GITHUB_MODELS_TOKEN ""          "GitHub Models 细粒度 PAT（只授 Models 只读），步骤 8 填写；留空则 chat-github 不可用"

git check-ignore -q .env || { echo "FAIL .env 没有被 .gitignore 忽略，立即处理后再继续" >&2; exit 1; }
if [[ ${#added[@]} -gt 0 ]]; then
  echo "PASS 已写入：${added[*]}"
  if [[ " ${added[*]} " == *" LITELLM_SALT_KEY "* ]]; then
    echo "提醒：现在把 LITELLM_SALT_KEY 抄进密码管理器（运行 grep SALT .env 查看）。它丢了，库里加密的凭据就作废。"
  fi
else
  echo "PASS .env 已完整，没有改动"
fi
echo ".env 权限：$(stat -c %a .env)（应为 600）"
