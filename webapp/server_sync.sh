#!/bin/bash
# 服务器端每 6 小时同步：快照网页数据 → 拉代码 → 原子回放合并 → 建库/推送。
# SQLite 只作服务索引；权威数据是 reports JSONL + manual_review.json。

set -euo pipefail
cd "$(dirname "$0")/.."

RETRY=3
DELAY=20
GIT_TIMEOUT=120
LOG=/tmp/server_sync.log
DEPLOY_MARKER=webapp/.deployed-head
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
    --records "$SNAPSHOT_DIR/records_delta.jsonl" \
    --manual "$SNAPSHOT_DIR/manual_delta.json" >> "$LOG" 2>&1
  SNAPSHOT_REPLAYED=1
}
generate_reports() {
  .venv/bin/python scripts/generate_profiles.py \
    --results reports/sites/sites_latest.jsonl \
    --profiles-dir reports/sites/profiles \
    --summary reports/sites/sites_summary.md >> "$LOG" 2>&1
}

# Serialize the complete snapshot/pull/replay/rebuild transaction with all web
# mutations.  The service keeps serving reads; only the brief write requests
# wait until the authoritative files and SQLite index agree again.
export SITES_DATA_LOCK="$(pwd)/webapp/.data-sync.lock"
exec 8>> /tmp/measure-server-sync.lock
if ! flock -n 8; then
  log "已有同步任务运行，本次跳过"
  exit 0
fi
exec 9>> "$SITES_DATA_LOCK"
flock -x 9
export SITES_SYNC_LOCK_HELD=1

log "=== 开始同步 ==="
# head 提前退出会让 git status 收到 SIGPIPE（改动文件多时），
# pipefail 下脚本会以 141 中止——用 || true 吞掉该退出码
LOCAL_DATA_CHANGES=$(git status --porcelain -- "${AUTHORITATIVE_FILES[@]}" | head -40) || true
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
  .venv/bin/python scripts/snapshot_data_changes.py \
    --output-records "$SNAPSHOT_DIR/records_delta.jsonl" \
    --output-manual "$SNAPSHOT_DIR/manual_delta.json" >> "$LOG" 2>&1
  HAS_SNAPSHOT=1
  log "已快照服务器网页数据: $LOCAL_DATA_CHANGES"
  git restore --worktree -- "${AUTHORITATIVE_FILES[@]}"
else
  log "服务器网页数据无变化"
fi

# 先以干净工作树拉取 Mac/GitHub；失败时立即回放快照，数据保持为本地未提交变更。
if ! retry "git pull --rebase" timeout "$GIT_TIMEOUT" git pull --rebase; then
  if [ "$HAS_SNAPSHOT" -eq 1 ]; then
    replay_snapshot
    log "拉取失败，权威网页数据已从快照恢复，留待下次同步"
  fi
  exit 1
fi

# 拉取成功后只回放相对旧 HEAD 真正变化的 (hostname, entry_kind)；服务器网页增量
# 覆盖同键远端记录，远端其他网站/另一侧结果完整保留。人工数据按网站同样合并。
if [ "$HAS_SNAPSHOT" -eq 1 ]; then
  replay_snapshot
  generate_reports
  CHANGED=$(git status --porcelain -- "${DATA_FILES[@]}" | head -40) || true
  if [ -n "$CHANGED" ]; then
    git add -- "${DATA_FILES[@]}"
    git commit -m "data: 服务器数据同步 $(date '+%F %H:%M')" >> "$LOG" 2>&1
    log "网页数据已合并并提交: $CHANGED"
  else
    log "快照内容已包含在远端，无需重复提交"
  fi
fi

NEW_HEAD=$(git rev-parse HEAD)
DEPLOYED_HEAD=$(sed -n '1p' "$DEPLOY_MARKER" 2>/dev/null || true)
NEEDS_DEPLOY=0
if [ "$DEPLOYED_HEAD" != "$NEW_HEAD" ]; then
  NEEDS_DEPLOY=1
elif ! curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:8000/api/stats; then
  NEEDS_DEPLOY=1
  log "部署标记匹配但 API 不健康，将重新部署"
fi

if [ "$NEEDS_DEPLOY" -eq 1 ]; then
  log "部署未完成: ${DEPLOYED_HEAD:-无标记} -> $NEW_HEAD，重建 SQLite 并重启服务"
  .venv/bin/python scripts/build_site_database.py >> "$LOG" 2>&1
  sudo -n systemctl restart sites-webapp
  retry "服务健康检查" curl -fsS --max-time 10 -o /dev/null \
    http://127.0.0.1:8000/api/stats
  printf '%s\n' "$NEW_HEAD" > "$DEPLOY_MARKER.tmp"
  mv -- "$DEPLOY_MARKER.tmp" "$DEPLOY_MARKER"
  log "部署及健康检查完成: $NEW_HEAD"
else
  log "当前提交已部署且 API 健康，无需重启"
fi

# Git push only publishes the already-created commit and does not touch the
# working-tree authority. Release the data lock first so a slow network retry
# does not stall web submissions; fd 8 still prevents overlapping sync jobs.
flock -u 9
unset SITES_SYNC_LOCK_HELD

if [ "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" -gt 0 ]; then
  if retry "git push" timeout "$GIT_TIMEOUT" git push; then
    log "服务器数据已推送到 GitHub"
  else
    log "推送失败，本地提交保留，留待下次同步"
    exit 1
  fi
else
  log "没有待推送提交"
fi

log "=== 同步完成 ==="
