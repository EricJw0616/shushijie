#!/bin/sh
# macOS / Linux：前台启动，Ctrl+C 停止。
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
PORT="${1:-8942}"
HOST="${2:-127.0.0.1}"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$APP_DIR/run.py" --host "$HOST" --port "$PORT"
elif command -v python >/dev/null 2>&1; then
  exec python "$APP_DIR/run.py" --host "$HOST" --port "$PORT"
else
  echo '需要 Python 3.9 或更新版本，请先按 app/README.md 安装。' >&2
  exit 2
fi
