#!/usr/bin/env bash
# 生成或迁移网关密钥到 .secrets/（P3 起取代 gen-env.sh）。人工运行，执行器禁止运行。
#   bash scripts/gen-secrets.sh              # 迁移 .env 里的旧值；缺什么补什么；没有 Anthropic key 时提示输入
#   bash scripts/gen-secrets.sh --anthropic  # 只更换 Anthropic key（轮换时用）
# 规则：已存在的文件一律不动。Salt Key 与 Postgres 密码在数据卷已存在时绝不重新生成，找不到旧值就失败。
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p .secrets && chmod 700 .secrets

fail() { echo "FAIL $*" >&2; exit 1; }
pass() { echo "PASS $*"; }
envval() {  # 先找 .env，再找迁移时留下的 .env.p2-backup
  local f v
  for f in .env .env.p2-backup; do
    [[ -f $f ]] || continue
    v="$(sed -n "s/^$1=//p" "$f" | tail -n1 | tr -d '\r')"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done
  return 0
}
rand() { python3 -c "import secrets; print(secrets.token_hex(24))"; }
head6() { printf '%s' "$1" | cut -c1-6; }

git check-ignore -q .secrets/x || fail ".secrets/ 没有被 .gitignore 忽略"

ask_anthropic() {
  echo "粘贴 Anthropic Console 里新建的网关专用 key（sk-ant- 开头，输入不回显；直接回车表示暂不配置）："
  local k; read -rs k; echo
  k="$(printf '%s' "$k" | tr -d '[:space:]')"
  if [[ -n "$k" && "$k" != sk-ant-* ]]; then fail "看起来不是 Anthropic key（应以 sk-ant- 开头），未写入"; fi
  printf '%s' "$k" > .secrets/anthropic_api_key; chmod 600 .secrets/anthropic_api_key
  if [[ -n "$k" ]]; then pass "anthropic_api_key 已写入（$(head6 "$k")…）"; else echo "WARN anthropic_api_key 为空：chat-cloud 暂不可用"; fi
}

if [[ "${1:-}" == "--anthropic" ]]; then ask_anthropic; echo "生效：docker compose up -d litellm"; exit 0; fi

volume_exists=0
docker volume inspect llm-gateway-governance_pg-data >/dev/null 2>&1 && volume_exists=1

migrated=()
put() {  # put 文件名 .env变量名 可否新生成(yes/no)
  local f=".secrets/$1" v
  if [[ -s "$f" ]]; then echo "保留 $1（已存在，不改）"; return; fi
  v="$(envval "$2")"
  if [[ -n "$v" ]]; then
    printf '%s' "$v" > "$f"; migrated+=("$2")
    [[ "$(cat "$f")" == "$v" ]] || fail "$1 写入后与 .env 不一致"
    pass "$1 从 .env 迁移（$(head6 "$v")…，逐字一致）"
  elif [[ "$3" == yes || $volume_exists == 0 ]]; then
    if [[ "$1" == litellm_master_key || "$1" == litellm_salt_key ]]; then v="sk-$(rand)"; else v="$(rand)"; fi
    printf '%s' "$v" > "$f"; pass "$1 新生成（$(head6 "$v")…）"
    [[ "$1" == litellm_salt_key ]] && echo "提醒：把 Salt Key 抄进密码管理器（cat .secrets/litellm_salt_key）"
  else
    fail "$1：.env 里没有 $2，而数据卷 pg-data 已存在。重新生成会让库里的数据无法使用，请找回旧值后写入 $f"
  fi
  chmod 600 "$f"
}

put litellm_master_key LITELLM_MASTER_KEY yes
put litellm_salt_key   LITELLM_SALT_KEY   no
put postgres_password  POSTGRES_PASSWORD  no
[[ -f .secrets/anthropic_api_key ]] || ask_anthropic

# 迁移完成后，.env 里不再保留这些值：先整份备份（600，被 .gitignore 的 .env.* 忽略），再删除 .env
if [[ -f .env && ${#migrated[@]} -gt 0 ]]; then
  cp -p .env .env.p2-backup && chmod 600 .env.p2-backup
  left="$(grep -vE '^(LITELLM_MASTER_KEY|LITELLM_SALT_KEY|POSTGRES_PASSWORD)=' .env | grep -vE '^\s*(#|$)' || true)"
  if [[ -z "$left" ]]; then rm -f .env; pass ".env 已备份为 .env.p2-backup 后删除（compose 不再需要它）"
  else grep -vE '^(LITELLM_MASTER_KEY|LITELLM_SALT_KEY|POSTGRES_PASSWORD)=' .env.p2-backup > .env; chmod 600 .env
       echo "WARN .env 还有其他变量，已只删除三个密钥：$left"; fi
  git check-ignore -q .env.p2-backup || fail ".env.p2-backup 没有被忽略"
fi

for f in litellm_master_key litellm_salt_key postgres_password anthropic_api_key; do
  [[ -f .secrets/$f ]] || fail "缺少 .secrets/$f"
  [[ "$(stat -c %a .secrets/$f)" == 600 ]] || fail ".secrets/$f 权限不是 600"
done
pass "四个密钥文件就绪，权限 600。下一步：docker compose up -d"
