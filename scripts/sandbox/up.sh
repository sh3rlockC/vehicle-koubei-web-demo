#!/usr/bin/env bash
set -euo pipefail

SANDBOX_ENV_PATH="${SANDBOX_ENV_PATH:-.sandbox/vehicle-koubei/.env}"

if [[ ! -f "$SANDBOX_ENV_PATH" ]]; then
  printf 'sandbox env missing: %s\nrun scripts/sandbox/sync-server-env.sh first\n' "$SANDBOX_ENV_PATH" >&2
  exit 1
fi

docker compose \
  -p vehicle-koubei-sandbox \
  --env-file "$SANDBOX_ENV_PATH" \
  -f docker-compose.yml \
  -f ops/sandbox/docker-compose.sandbox.yml \
  up -d --build

docker compose \
  -p vehicle-koubei-sandbox \
  --env-file "$SANDBOX_ENV_PATH" \
  -f docker-compose.yml \
  -f ops/sandbox/docker-compose.sandbox.yml \
  ps
