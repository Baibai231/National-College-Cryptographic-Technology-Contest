#!/bin/bash
# Mac 端：打包项目（不含 .venv/.git/日志），供 scp 到服务器
# 用法: ./webapp/package.sh
# 输出: /tmp/measure.tar.gz
set -e
cd "$(dirname "$0")/.."
echo "打包项目（排除 .venv/.git/logs/browser-linux）..."
tar czf /tmp/measure.tar.gz \
  --exclude='.venv' --exclude='.git' \
  --exclude='logs' --exclude='webapp/browser-linux' \
  --exclude='*.pyc' --exclude='__pycache__' \
  .
echo "完成: /tmp/measure.tar.gz ($(du -h /tmp/measure.tar.gz | cut -f1))"
echo "上传: scp /tmp/measure.tar.gz ubuntu@服务器IP:~/"
echo "服务器解压: cd ~ && tar xzf measure.tar.gz （覆盖更新）"
