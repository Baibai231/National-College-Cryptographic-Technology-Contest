#!/bin/bash
# 手动全量重测：测量 151 站 → 生成档案 → 重建数据库 → 重启服务。
# GitHub/服务器同步由 server_sync.sh 负责，避免在测量中途覆盖网页增量。
# 用法: ./webapp/update_data.sh [单独站点清单] [输出JSONL]

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${2:-reports/sites/sites_latest.jsonl}"
WORKERS="${SITES_WORKERS:-3}"
if [[ -n "${1:-}" ]]; then
  INPUTS=(--input "$1")
else
  INPUTS=(
    --input misc/sites_base_60.txt
    --input misc/sites_extra_60.txt
    --input misc/sites_new_30.txt
    --input misc/sites_extra.txt
  )
fi

echo "== 1/4 全量测量 → $OUT（并发 $WORKERS）"
.venv/bin/python scripts/run_measurement.py \
  "${INPUTS[@]}" --kinds signup,login --output "$OUT" \
  --workers "$WORKERS" --overwrite

echo "== 2/4 生成逐站档案与汇总"
.venv/bin/python scripts/generate_profiles.py \
  --results "$OUT" \
  --profiles-dir reports/sites/profiles \
  --summary reports/sites/sites_summary.md

echo "== 3/4 重建可随时生成的 SQLite 服务索引"
.venv/bin/python scripts/build_site_database.py --input "$OUT"

echo "== 4/4 重启服务"
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet sites-webapp; then
  sudo systemctl restart sites-webapp
else
  echo "  未检测到运行中的 systemd 服务；本地可执行 ./webapp/run_server.sh 8000"
fi

echo "完成。版本仍取 misc/measure_version.txt；验证: curl -fsS http://127.0.0.1:8000/api/stats"
