#!/bin/bash
# 当前工作区副本使用 8943；Ctrl+C 停止服务。
set -e
cd "$(dirname "$0")"
export BOOKDISTILL_ROOT="$PWD"
PYTHON_BIN="/usr/bin/python3"
if [[ -x .venv/bin/python3 ]]; then
  PYTHON_BIN="$PWD/.venv/bin/python3"
fi
exec "$PYTHON_BIN" -u app/server.py --host 127.0.0.1 --port "${1:-8943}"
