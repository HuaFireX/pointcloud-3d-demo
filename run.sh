#!/usr/bin/env bash
# Linux 启动脚本
set -e
cd "$(dirname "$0")"

if [ ! -f .venv/bin/python ]; then
    echo "未找到 .venv，请先运行 bash setup.sh"
    exit 1
fi

source .venv/bin/activate
python app.py
