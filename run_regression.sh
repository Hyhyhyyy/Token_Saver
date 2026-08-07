#!/usr/bin/env bash
# SkillForge v2.2 全量回归（D-2/D-3）：固定合成 fixture + mock embedding，可重复验证。
set -euo pipefail

cd "$(dirname "$0")"

# 若环境未装 pytest，本地位兜底安装（不写入 runtime requirements）
if ! python -m pytest --version >/dev/null 2>&1; then
  echo "[regression] 未检测到 pytest，尝试本地安装（仅测试运行环境）..."
  pip install pytest httpx >/dev/null 2>&1 || true
fi

python -m pytest tests/ -q
