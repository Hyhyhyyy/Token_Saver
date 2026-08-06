"""清洗预算覆盖管理（自进化闭环：回归 → 回调预算 → 注入 cleaner）。

- 覆盖值存于 DATA_DIR/skill_budget_overrides.json。
- effective_target(skill_id)：有覆盖取覆盖值，否则 config.DESC_TARGET_TOKENS。
- auto_recall(skill_id)：自动回调一档（+BUDGET_RECALL_STEP），封顶 DESC_HARD_TOKENS。
- manual_recall(skill_id, target?)：手动回调（PUT /api/sim/budget），target 缺省 +STEP。
server 在 /api/clean 前用 effective_target() 计算 target 并传入 cleaner.clean_skill。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import (
    BUDGET_OVERRIDES_PATH,
    BUDGET_RECALL_STEP,
    DESC_TARGET_TOKENS,
    DESC_HARD_TOKENS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_overrides() -> dict:
    """读取预算覆盖表；文件缺失/损坏返回空 dict。"""
    if BUDGET_OVERRIDES_PATH.exists():
        try:
            data = json.loads(BUDGET_OVERRIDES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def effective_target(skill_id: str) -> int:
    """该技能实际使用的压缩目标 token：有覆盖取覆盖值，否则默认 DESC_TARGET_TOKENS。"""
    entry = load_overrides().get(skill_id)
    if isinstance(entry, dict) and isinstance(entry.get("target"), int):
        return entry["target"]
    return DESC_TARGET_TOKENS


def save_override(skill_id: str, target: int, reason: str, regress_count: int = 0) -> dict:
    """写入/更新某技能的预算覆盖，返回该条目。"""
    ov = load_overrides()
    entry = {
        "target": int(target),
        "reason": reason,
        "regress_count": int(regress_count),
        "updated_at": _now(),
    }
    ov[skill_id] = entry
    BUDGET_OVERRIDES_PATH.write_text(
        json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def auto_recall(skill_id: str) -> dict:
    """自动回调：当前目标 +STEP，封顶 DESC_HARD_TOKENS；返回写入后的条目。"""
    cur = effective_target(skill_id)
    new_target = min(DESC_HARD_TOKENS, cur + BUDGET_RECALL_STEP)
    prev = load_overrides().get(skill_id, {})
    regress_count = int(prev.get("regress_count", 0)) + 1
    return save_override(skill_id, new_target, "调度回归自动回调", regress_count=regress_count)


def manual_recall(skill_id: str, target: int | None = None) -> dict:
    """手动回调（PUT /api/sim/budget）。target 缺省为 当前目标 +STEP；钳制到 [目标, 硬上限]。"""
    if target is None:
        base = effective_target(skill_id)
        target = base + BUDGET_RECALL_STEP
    target = min(DESC_HARD_TOKENS, max(DESC_TARGET_TOKENS, int(target)))
    prev = load_overrides().get(skill_id, {})
    regress_count = int(prev.get("regress_count", 0))
    return save_override(skill_id, target, "手动回调压缩预算", regress_count=regress_count)
