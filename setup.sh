#!/usr/bin/env bash
# Linux 一键安装脚本：创建 venv + 安装依赖
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "[1/3] 创建虚拟环境 .venv ..."
    for py in python3.12 python3.11 python3.10 python3; do
        if command -v "$py" >/dev/null 2>&1; then
            "$py" -m venv .venv && break
        fi
    done
    if [ ! -d .venv ]; then
        echo "创建 venv 失败，请手动安装 Python 3.10~3.12"
        exit 1
    fi
else
    echo "[1/3] .venv 已存在，跳过创建"
fi

echo "[2/3] 升级 pip ..."
source .venv/bin/activate
python -m pip install --upgrade pip

echo "[3/3] 安装依赖 ..."
pip install -r requirements.txt

echo
echo "安装完成，运行 bash run.sh 启动 demo"
