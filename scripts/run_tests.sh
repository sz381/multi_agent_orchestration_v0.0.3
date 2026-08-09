#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

./.venv/bin/python -m pytest \
    -v \
    --tb=short \
    --color=yes \
    "$@"
