#!/usr/bin/env bash
# SkillForge 一键本地启动脚本（无需 Docker）
set -e
cd "$(dirname "$0")"

echo "==> 创建隔离虚拟环境"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 安装依赖"
pip install --quiet -r requirements.txt

echo "==> 启动服务 (http://localhost:8000)"
export SKILLS_DIRS="${SKILLS_DIRS:-$HOME/.workbuddy/skills}"
export DATA_DIR="${DATA_DIR:-$(pwd)/data}"
exec uvicorn skillforge.server:app --host 127.0.0.1 --port 8000
