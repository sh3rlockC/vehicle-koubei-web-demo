#!/usr/bin/env bash
set -euo pipefail

SANDBOX_ENV_PATH="${SANDBOX_ENV_PATH:-.sandbox/vehicle-koubei/.env}"

docker compose \
  -p vehicle-koubei-sandbox \
  --env-file "$SANDBOX_ENV_PATH" \
  -f docker-compose.yml \
  -f ops/sandbox/docker-compose.sandbox.yml \
  down
