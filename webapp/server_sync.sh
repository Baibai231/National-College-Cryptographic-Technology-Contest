#!/bin/bash
# 服务器端每 6 小时同步：快照网页数据 → 拉代码 → 原子回放合并 → 建库/推送。
# SQLite 只作服务索引；权威数据是 reports JSONL + manual_review.json。

set -euo pipefail
cd ~/measure

RETRY=3
DELAY=20
LOG=/tmp/server_sync.log
AUTHORITATIVE_FILES=(
  reports/sites/sites_latest.jsonl
  misc/manual_review.json
)
GENERATED_FILES=(
  reports/sites/sites_summary.md
  reports/sites/profiles
)
DATA_FILES=("${AUTHORITATIVE_FILES[@]}" "${GENERATED_FILES[@]}")

log() { echo "[$(date '+%F %T')] $1" >> "$LOG"; }
retry() {
  local label="$1"
  shift
  local i
  for i in $(seq 1 "$RETRY"); do
    if "$@" >> "$LOG" 2>&1; then
      return 0
    fi
    log "$label 第${i}次失败，${DELAY}s 后重试"
    sleep "$DELAY"
  done
  return 1
}
replay_snapshot() {
  .venv/bin/python scripts/merge_data_files.py \
    --records "$SNAPSHOT_DIR/sites_latest.jsonl" \
    --manual "$SNAPSHOT_DIR/manual_review.json" >> "$LOG" 2>&1
  SNAPSHOT_REPLAYED=1
}
generate_reports() {
  .venv/bin/python scripts/generate_profiles.py \
    --results reports/sites/sites_latest.jsonl \
    --profiles-dir reports/sites/profiles \
    --summary reports/sites/sites_summary.md >> "$LOG" 2>&1
}

log "=== 开始同步 ==="
OLD_HEAD=$(git rev-parse HEAD)
LOCAL_DATA_CHANGES=$(git status --porcelain -- "${DATA_FILES[@]}" | head -40)
HAS_SNAPSHOT=0

if [ -n "$LOCAL_DATA_CHANGES" ]; then
  # 网页只即时写权威 JSON/JSONL。拉取前先复制到独立临时目录，再把工作树恢复为
  # 当前提交，以避免 Mac 和服务器同时改同一 JSONL 时发生 rebase 冲突。
  SNAPSHOT_DIR=$(mktemp -d /tmp/measure-sync.XXXXXX)
  SNAPSHOT_REPLAYED=0
  cleanup_snapshot() {
    if [ "$SNAPSHOT_REPLAYED" -eq 1 ]; then
      rm -r -- "$SNAPSHOT_DIR"
    else
      log "同步异常发生在回放前，安全快照保留在 $SNAPSHOT_DIR"
    fi
  }
  trap cleanup_snapshot EXIT
  cp reports/sites/sites_latest.jsonl "$SNAPSHOT_DIR/sites_latest.jsonl"
  cp misc/manual_review.json "$SNAPSHOT_DIR/manual_review.json"
  HAS_SNAPSHOT=1
  log "已快照服务器网页数据: $LOCAL_DATA_CHANGES"
  git restore --worktree -- "${DATA_FILES[@]}"
else
  log "服务器网页数据无变化"
fi

# 先以干净工作树拉取 Mac/GitHub；失败时立即回放快照，数据保持为本地未提交变更。
if ! retry "git pull --rebase" git pull --rebase; then
  if [ "$HAS_SNAPSHOT" -eq 1 ]; then
    replay_snapshot
    log "拉取失败，权威网页数据已从快照恢复，留待下次同步"
  fi
  exit 1
fi

# 拉取成功后按 (hostname, entry_kind) 回放；服务器网页记录覆盖同键远端记录，
# 远端其他网站/另一侧结果仍完整保留。人工数据按网站同样合并。
if [ "$HAS_SNAPSHOT" -eq 1 ]; then
  replay_snapshot
  generate_reports
  CHANGED=$(git status --porcelain -- "${DATA_FILES[@]}" | head -40)
  if [ -n "$CHANGED" ]; then
    git add -- "${DATA_FILES[@]}"
    git commit -m "data: 服务器数据同步 $(date '+%F %H:%M')" >> "$LOG" 2>&1
    log "网页数据已合并并提交: $CHANGED"
  else
    log "快照内容已包含在远端，无需重复提交"
  fi
fi

NEW_HEAD=$(git rev-parse HEAD)
if [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
  log "仓库更新: $OLD_HEAD -> $NEW_HEAD，重建 SQLite 并重启服务"
  .venv/bin/python scripts/build_site_database.py >> "$LOG" 2>&1
  sudo systemctl restart sites-webapp
else
  log "代码和数据均无变化，无需重启"
fi

if [ "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" -gt 0 ]; then
  if retry "git push" git push; then
    log "服务器数据已推送到 GitHub"
  else
    log "推送失败，本地提交保留，留待下次同步"
    exit 1
  fi
else
  log "没有待推送提交"
fi

log "=== 同步完成 ==="
