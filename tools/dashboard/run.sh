#!/usr/bin/env bash
# Запуск dashboard: tools/dashboard/run.sh [порт]   (по умолчанию 8765)
# Слушает ТОЛЬКО 127.0.0.1. cwd = work_agent (корень агента).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # tools/dashboard
ROOT="$(dirname "$(dirname "$DIR")")"                   # work_agent
cd "$ROOT"
PYTHON="${AGENT_PYTHON:-$ROOT/.venv/bin/python}"
exec "$PYTHON" -m uvicorn tools.dashboard.app:app \
    --host 127.0.0.1 --port "${1:-8765}"
