#!/bin/bash
# 服务器端：定时同步脚本（cron 每 6 小时执行）
# 功能：
#   1. git pull 拉最新代码 → 有变化则重建数据库+重启服务
#   2. 聚合提交服务器数据（sites_latest.jsonl/manual_review.json）→ push GitHub
# 特性：
#   - 数据没变化不提交（避免空 commit）
#   - 网络失败自动重试 3 次，仍失败则退出（下次 cron 补）
#   - 只提交数据文件，不提交 sites.db（数据库可由 jsonl 重建）

set -e
cd ~/measure

RETRY=3
DELAY=20
LOG=/tmp/server_sync.log

log() { echo "[$(date '+%F %T')] $1" >> "$LOG"; }

# ── 1. 拉代码（重试）──
for i in $(seq 1 $RETRY); do
  if git pull --no-edit >> "$LOG" 2>&1; then
    pulled="yes"
    break
  fi
  log "git pull 第${i}次失败，${DELAY}s后重试"
  sleep $DELAY
done

if [ "$pulled" = "yes" ]; then
  # 代码有变化？（git pull 会输出 Already up to date 或更新信息）
  if git log -1 --format=%H > /tmp/last_head.txt 2>/dev/null; then
    :
  fi
  # 简单判断：检查 git pull 是否真的更新了（用 pull 输出）
  # 用 git rev-parse 对比：pull 前后 HEAD
  OLD_HEAD=$(cat /tmp/server_head.txt 2>/dev/null || echo none)
  NEW_HEAD=$(git rev-parse HEAD)
  if [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
    log "代码更新: $OLD_HEAD -> $NEW_HEAD，重建数据库并重启"
    .venv/bin/python scripts/build_site_database.py >> "$LOG" 2>&1 || true
    sudo systemctl restart sites-webapp || true
    echo "$NEW_HEAD" > /tmp/server_head.txt
  else
    log "代码无变化"
  fi
else
  log "git pull 全部失败（网络），跳过代码更新"
fi

# ── 2. 聚合提交数据 → push（重试）──
DATA_FILES="reports/sites/sites_latest.jsonl misc/manual_review.json reports/sites/sites_summary.md"
CHANGED=$(git status --porcelain $DATA_FILES | head -20)
if [ -n "$CHANGED" ]; then
  log "检测到数据变化，准备提交:"
  log "$CHANGED"
  git add $DATA_FILES
  git commit -m "data: 服务器数据同步 $(date '+%F %H:%M')" >> "$LOG" 2>&1 || true
  for i in $(seq 1 $RETRY); do
    if git push >> "$LOG" 2>&1; then
      log "数据已 push 到 GitHub"
      break
    fi
    log "git push 第${i}次失败，${DELAY}s后重试"
    sleep $DELAY
  done
else
  log "数据无变化，跳过提交"
fi

log "=== 同步完成 ==="
