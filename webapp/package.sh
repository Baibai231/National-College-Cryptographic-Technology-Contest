#!/bin/bash
# Mac 端：打包项目（严格排除 .venv/.git 等），供 scp 到服务器
# 用法: ./webapp/package.sh
# 输出: /tmp/measure.tar.gz
# 服务器解压: mkdir -p ~/measure && tar xzf ~/measure.tar.gz -C ~/measure
set -e
cd "$(dirname "$0")/.."

echo "打包项目（排除 .venv/.git/logs/browser-linux/pycache）..."
tar czf /tmp/measure.tar.gz \
  --exclude='./.venv' --exclude='./.git' \
  --exclude='./logs' --exclude='./webapp/browser-linux' \
  --exclude='*.pyc' --exclude='__pycache__' \
  --exclude='.DS_Store' \
  .
echo "完成: /tmp/measure.tar.gz ($(du -h /tmp/measure.tar.gz | cut -f1))"
echo ""
echo "上传: scp /tmp/measure.tar.gz ubuntu@服务器IP:~/"
echo "服务器解压(关键!):"
echo "  mkdir -p ~/measure && tar xzf ~/measure.tar.gz -C ~/measure"
echo "  cd ~/measure && .venv/bin/python scripts/build_site_database.py && sudo systemctl restart sites-webapp"
