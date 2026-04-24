#!/bin/sh
set -eu

if [ "${OPENCLAW_ADAPTER_ENABLED:-false}" != "true" ] && ! command -v agent-browser >/dev/null 2>&1; then
  echo "WARNING: agent-browser not found in the worker image; Autohome collection jobs will fail until this CLI is provided." >&2
fi

exec python worker.py
