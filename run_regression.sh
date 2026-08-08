#!/usr/bin/env bash
# SkillForge v2.3 全量回归（A/B/C/D 分组，fail-fast=false）：固定合成 fixture + mock embedding，可重复验证。
# 按方向分组运行并标注失败方向（TestA*/TestB*/TestC*/TestD* 经 pytest.mark.a/b/c/d）。
set -uo pipefail

cd "$(dirname "$0")"

# 若环境未装 pytest，本地位兜底安装（不写入 runtime requirements）
if ! python -m pytest --version >/dev/null 2>&1; then
  echo "[regression] 未检测到 pytest，尝试本地安装（仅测试运行环境）..."
  pip install pytest httpx >/dev/null 2>&1 || true
fi

FAILED=0
for d in a b c d; do
  echo ""
  echo "===== Direction $d (pytest -m $d) ====="
  if python -m pytest tests/ -q -m "$d"; then
    echo "[regression] Direction $d: PASS"
  else
    echo "[regression] Direction $d: FAIL"
    FAILED=1
  fi
done

echo ""
if [ "$FAILED" -ne 0 ]; then
  echo "[regression] 存在失败方向，请查看上方标注（A/B/C/D）。"
  exit 1
else
  echo "[regression] 全部方向通过。"
fi
