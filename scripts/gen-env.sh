#!/usr/bin/env bash
# P3 起密钥不再放在 .env，改为 .secrets/ 下的文件并以 Compose secrets 挂载。保留本文件只为兼容旧文档。
echo "gen-env.sh 已由 gen-secrets.sh 取代，转去运行它 ..." >&2
exec bash "$(dirname "$0")/gen-secrets.sh" "$@"
