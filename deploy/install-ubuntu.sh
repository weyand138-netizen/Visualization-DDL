#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config="${1:-$root/.env}"
route="${2:-airi}"
if [[ ! -f "$config" ]]; then
    echo 'Create a private environment file from .env.example first.' >&2
    exit 1
fi
args=(--project-name visualization-ddl --env-file "$config" -f "$root/deploy/compose.ubuntu.yaml")
if [[ "$route" == astrbot ]]; then
    args+=(-f "$root/deploy/compose.astrbot.yaml")
elif [[ "$route" != airi ]]; then
    echo 'Usage: bash deploy/install-ubuntu.sh ENV_FILE [airi|astrbot]' >&2
    exit 1
fi
docker compose "${args[@]}" up -d --build
