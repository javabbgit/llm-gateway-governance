#!/usr/bin/env bash
# 锁定 ollama/ollama 镜像（版本号 + 摘要）并写回 docker-compose.yml。
# 用法：bash scripts/pin-image.sh           # 取 GitHub 上 ollama/ollama 的最新正式版
#       bash scripts/pin-image.sh 0.32.5    # 指定版本
set -euo pipefail
cd "$(dirname "$0")/.."

ver="${1:-}"
if [[ -z "$ver" ]]; then
  ver="$(gh release view --repo ollama/ollama --json tagName --jq .tagName 2>/dev/null || true)"
fi
if [[ -z "$ver" ]]; then
  ver="$(curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest | jq -r .tag_name)"
fi
ver="${ver#v}"
if [[ ! "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "FAIL 版本号不是正式版格式：'${ver}'（不接受 rc 等预发布版）" >&2
  exit 1
fi

image="ollama/ollama:${ver}"
echo "拉取 ${image} ..."
docker pull "${image}"

# 优先用镜像仓库的清单摘要（多架构索引），取不到再用本地 RepoDigests
digest="$(docker buildx imagetools inspect "${image}" --format '{{json .Manifest}}' 2>/dev/null | jq -r '.digest // empty' || true)"
if [[ -z "${digest}" ]]; then
  digest="$(docker image inspect "${image}" --format '{{range .RepoDigests}}{{println .}}{{end}}' \
            | grep '^ollama/ollama@' | head -n1 | cut -d@ -f2)"
fi
if [[ ! "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "FAIL 取不到镜像摘要：'${digest}'" >&2
  exit 1
fi

pinned="${image}@${digest}"
sed -i -E "s#^([[:space:]]*image:[[:space:]]*)ollama/ollama[^[:space:]]*#\1${pinned}#" docker-compose.yml
if ! grep -qF "image: ${pinned}" docker-compose.yml; then
  echo "FAIL 未能写入 docker-compose.yml" >&2
  exit 1
fi
echo "PASS 已锁定 ${pinned}"
git --no-pager diff --stat -- docker-compose.yml || true

python3 scripts/p1check.py record pin --title "镜像锁定" --text "- 镜像：\`${pinned}\`
- 来源：ollama/ollama 在 GitHub 的最新正式版 v${ver}，锁定于 $(date '+%Y-%m-%d %H:%M')"
