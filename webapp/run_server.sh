#!/bin/bash
# 启动/重启注册流程测量平台（服务器部署用）
# 用法: ./webapp/run_server.sh [port]
# 默认端口 8000

set -e
cd "$(dirname "$0")/.."

PORT="${1:-8000}"
PID_FILE="/tmp/sites_webapp.pid"

if [ -f "$PID_FILE" ]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

echo "启动测量平台: http://0.0.0.0:${PORT}"
nohup .venv/bin/python -m uvicorn webapp.app:app \
  --host 0.0.0.0 --port "$PORT" \
  > /tmp/sites_webapp.log 2>&1 &
echo $! > "$PID_FILE"
echo "PID: $(cat "$PID_FILE")  (日志: /tmp/sites_webapp.log)"
