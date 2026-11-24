#!/bin/bash
cd "$(dirname "$0")" || exit 1
PORT="${1:-8942}"
python3 run.py --host 127.0.0.1 --port "$PORT" &
PID=$!
sleep 1
open "http://127.0.0.1:$PORT"
wait "$PID"
