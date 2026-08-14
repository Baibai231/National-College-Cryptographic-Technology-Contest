#!/bin/bash
# 一键更新测量数据：拉代码 → 跑批量测量 → 重建数据库 → 重启服务
# 用法: ./webapp/update_data.sh [站点清单] [输出JSONL]
# 默认: misc/sites_base_60.txt → reports/final/cn_latest.jsonl

set -e
cd "$(dirname "$0")/.."

SITES="${1:-misc/sites_base_60.txt}"
OUT="${2:-reports/final/cn_latest.jsonl}"
WORKERS=3

echo "== 1/4 拉取最新代码"
git pull

echo "== 2/4 批量测量 ($SITES → $OUT, 并发$WORKERS, 约30分钟)"
.venv/bin/python scripts/run_measurement.py \
  --input "$SITES" --output "$OUT" --workers "$WORKERS"

echo "== 3/4 重建数据库"
.venv/bin/python scripts/build_site_database.py --input "$OUT"

echo "== 4/4 重启服务"
if systemctl is-active --quiet sites-webapp; then
  sudo systemctl restart sites-webapp
else
  echo "  (未使用 systemd，请手动重启: ./webapp/run_server.sh 8000)"
fi

echo "完成。验证: curl -s http://127.0.0.1:8000/api/stats"
