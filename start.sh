#!/bin/bash
# Linux/macOS 启动脚本

echo "========================================"
echo "  DeepSeek娘 - B站自动运营程序"
echo "========================================"
echo ""

cd "$(dirname "$0")"

# 检查Python版本
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python3，请先安装Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "[✓] Python版本: $PYTHON_VERSION"

# 创建必要目录
echo "[1/2] 初始化目录..."
mkdir -p data/logs

# 启动程序
echo "[2/2] 启动程序（缺少的基础依赖会自动安装）..."
echo ""
python3 main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 程序运行出错"
    exit 1
fi
