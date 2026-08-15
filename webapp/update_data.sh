#!/bin/bash
# 手动全量重测：测量 151 站 → 生成档案 → 重建数据库 → 重启服务。
# GitHub/服务器同步由 server_sync.sh 负责，避免在测量中途覆盖网页增量。
# 用法: ./webapp/update_data.sh [单独站点清单] [输出JSONL]

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${2:-reports/sites/sites_latest.jsonl}"
MEASURE_OUT="$OUT"
WORKERS="${SITES_WORKERS:-3}"
STAGING=""
MEASUREMENT_COMPLETE=0
cleanup_staging() {
  if [[ -n "$STAGING" && -f "$STAGING" ]]; then
    if [[ "$MEASUREMENT_COMPLETE" -eq 1 ]]; then
      echo "完整临时测量保留在 $STAGING，可排查后重新合并"
    else
      rm -- "$STAGING"
    fi
  fi
}
trap cleanup_staging EXIT

# The authoritative JSONL is never truncated while the long measurement is in
# progress.  A complete staging result is merged later, preserving web-added
# sites that are not part of the fixed 151-site input lists.
if [[ "$OUT" == "reports/sites/sites_latest.jsonl" ]]; then
  STAGING=$(mktemp "reports/sites/sites_latest.jsonl.XXXXXX.tmp")
  MEASURE_OUT="$STAGING"
fi
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
  "${INPUTS[@]}" --kinds signup,login --output "$MEASURE_OUT" \
  --workers "$WORKERS" --overwrite
MEASUREMENT_COMPLETE=1

# Python owns the portable fcntl lock through promotion, report generation and
# database replacement. macOS has no flock command; this works on Mac/Linux.
echo "== 2-3/4 原子合并结果 → 生成档案 → 重建 SQLite"
if [[ -n "$STAGING" ]]; then
  .venv/bin/python scripts/finalize_measurement_data.py \
    --records "$STAGING" --target "$OUT"
  rm -- "$STAGING"
  STAGING=""
else
  .venv/bin/python scripts/finalize_measurement_data.py --target "$OUT"
fi
MEASUREMENT_COMPLETE=0

echo "== 4/4 重启服务"
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet sites-webapp; then
  sudo systemctl restart sites-webapp
else
  echo "  未检测到运行中的 systemd 服务；本地可执行 ./webapp/run_server.sh 8000"
fi

echo "完成。版本仍取 misc/measure_version.txt；验证: curl -fsS http://127.0.0.1:8000/api/stats"
