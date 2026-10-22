#!/usr/bin/env bash
# 按 models/models.txt 拉取模型，保存 ollama list 输出，并生成 models/lock.json。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "$(docker compose ps -q ollama)" ]]; then
  echo "FAIL ollama 容器未运行，先执行 docker compose up -d" >&2
  exit 1
fi

mapfile -t tags < <(sed -e 's/#.*//' models/models.txt | awk 'NF {print $1}')
if [[ ${#tags[@]} -eq 0 ]]; then
  echo "FAIL models/models.txt 里没有模型" >&2
  exit 1
fi

for t in "${tags[@]}"; do
  echo "=== ollama pull ${t}"
  docker compose exec -T ollama ollama pull "${t}"
done

docker compose exec -T ollama ollama list | tee models/ollama-list.txt
python3 scripts/p1check.py lock
