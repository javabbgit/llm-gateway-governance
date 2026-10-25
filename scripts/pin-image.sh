#!/usr/bin/env bash
# 锁定镜像（版本号 + 摘要）并写回 docker-compose.yml。
# 用法：bash scripts/pin-image.sh ollama   [版本]   # 默认取 GitHub 上 ollama/ollama 的最新正式版
#       bash scripts/pin-image.sh litellm  [标签]   # 默认取 BerriAI/litellm 标为 Latest 的正式版，如 v1.106.2
#       bash scripts/pin-image.sh postgres [大版本] # 默认 17，解析成具体小版本，例如 17.6
#       bash scripts/pin-image.sh presidio [版本]   # 默认取 MCR 上最新的正式版本号，如 2.2.362
#       bash scripts/pin-image.sh 0.40.8            # 兼容 P1 写法：等同 ollama 0.40.8
set -euo pipefail
cd "$(dirname "$0")/.."

svc="${1:-ollama}"
arg="${2:-}"
if [[ "$svc" =~ ^v?[0-9] ]]; then arg="$svc"; svc="ollama"; fi

fail() { echo "FAIL $*" >&2; exit 1; }

case "$svc" in
  ollama)
    repo="ollama/ollama"
    ver="$arg"
    [[ -z "$ver" ]] && ver="$(gh release view --repo ollama/ollama --json tagName --jq .tagName 2>/dev/null || true)"
    ver="${ver#v}"
    [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "版本号不是正式版格式：'${ver}'（不接受 rc 等预发布版）"
    tag="$ver"; source_note="ollama/ollama 的 GitHub 正式版 v${ver}"
    ;;
  litellm)
    repo="ghcr.io/berriai/litellm"
    tag="$arg"
    if [[ -z "$tag" ]]; then
      tag="$(gh release view --repo BerriAI/litellm --json tagName --jq .tagName 2>/dev/null || true)"
    fi
    [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-stable)?(\.[0-9]+)?$ ]] || fail "取不到 LiteLLM 的正式版标签：'${tag}'。到 github.com/BerriAI/litellm/releases 找标为 Latest 的 vX.Y.Z，再运行 bash scripts/pin-image.sh litellm <标签>"
    source_note="BerriAI/litellm 的 GitHub 发布 ${tag}（Latest 正式版）"
    ;;
  postgres)
    repo="postgres"
    major="${arg:-17}"
    [[ "$major" =~ ^[0-9]+$ ]] || fail "postgres 只接受大版本号，例如 17"
    echo "拉取 postgres:${major} 以解析具体小版本 ..."
    docker pull "postgres:${major}" >/dev/null
    pgv="$(docker image inspect "postgres:${major}" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^PG_VERSION=//p' | cut -d- -f1)"
    [[ "$pgv" =~ ^${major}\.[0-9]+$ ]] || fail "解析不出 Postgres 小版本：'${pgv}'"
    tag="$pgv"; source_note="Docker Hub 官方镜像 postgres:${major} 当前的小版本 ${pgv}"
    ;;
  presidio)
    repo="mcr.microsoft.com/presidio-analyzer"
    # 版本号以 MCR 上实际存在的标签为准：镜像发布比 PyPI 包慢，PyPI 的最新版可能没有对应镜像（P4 实测 2.2.364 不存在）
    mcr_tags="$(curl -fsS https://mcr.microsoft.com/v2/presidio-analyzer/tags/list 2>/dev/null | jq -r '.tags[]' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V || true)"
    [[ -n "$mcr_tags" ]] || fail "取不到 MCR 的标签列表：curl -s https://mcr.microsoft.com/v2/presidio-analyzer/tags/list"
    tag="${arg:-$(tail -1 <<<"$mcr_tags")}"
    grep -qx "$tag" <<<"$mcr_tags" || fail "MCR 没有 presidio-analyzer:${tag}。现有最新的几个：$(tail -5 <<<"$mcr_tags" | tr '\n' ' ')"
    source_note="Microsoft Presidio 官方镜像（MCR），取 MCR 标签列表里最新的正式版本号 ${tag}"
    ;;
  *) fail "未知服务：${svc}（可选 ollama、litellm、postgres、presidio）";;
esac

image="${repo}:${tag}"
echo "拉取 ${image} ..."
docker pull "${image}"

# 优先用镜像仓库的清单摘要（多架构索引），取不到再用本地 RepoDigests
digest="$(docker buildx imagetools inspect "${image}" --format '{{json .Manifest}}' 2>/dev/null | jq -r '.digest // empty' || true)"
if [[ -z "${digest}" ]]; then
  digest="$(docker image inspect "${image}" --format '{{range .RepoDigests}}{{println .}}{{end}}' \
            | grep "^${repo}@" | head -n1 | cut -d@ -f2 || true)"
fi
[[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "取不到镜像摘要：'${digest}'"

pinned="${image}@${digest}"
repo_re="$(printf '%s' "$repo" | sed 's/[.]/\\./g')"
sed -i -E "s#^([[:space:]]*image:[[:space:]]*)${repo_re}[:@][^[:space:]]*#\1${pinned}#" docker-compose.yml
grep -qF "image: ${pinned}" docker-compose.yml || fail "未能写入 docker-compose.yml（compose 里找不到 ${repo} 的 image 行）"
echo "PASS 已锁定 ${pinned}"
git --no-pager diff --stat -- docker-compose.yml || true

python3 scripts/p2check.py record "pin-${svc}" --title "镜像锁定：${svc}" --text "- 镜像：\`${pinned}\`
- 来源：${source_note}，锁定于 $(date '+%Y-%m-%d %H:%M')"
