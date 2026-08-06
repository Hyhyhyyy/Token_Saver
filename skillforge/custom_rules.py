"""自定义校验规则沉淀（F3 冲突检测 → 闭环：沉淀为可加载的校验规则）。

- 规则存于 DATA_DIR/custom_rules.json，dim="冲突"，source="conflict-detector"。
- load_custom_rules()：读列表（缺省空）。
- deposit_custom_rule(keyword_cluster, suggestion, rule?, severity?)：生成 CONFLICT-NN 并落盘。
spec.get_validation_rules() 会合并这些规则并标注 source=custom，validator 据此生效。
"""
from __future__ import annotations

import json
import re

from .config import CUSTOM_RULES_PATH


def load_custom_rules() -> list[dict]:
    """读取自定义规则列表；文件缺失/损坏返回空列表。"""
    if CUSTOM_RULES_PATH.exists():
        try:
            data = json.loads(CUSTOM_RULES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def next_conflict_id() -> str:
    """生成下一个 CONFLICT-NN（NN 为现有最大序号 +1，两位补零）。"""
    max_n = 0
    for r in load_custom_rules():
        m = re.match(r"CONFLICT-(\d+)", str(r.get("id", "")))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"CONFLICT-{max_n + 1:02d}"


def deposit_custom_rule(keyword_cluster, suggestion: str,
                        rule: str | None = None, severity: str = "warning") -> dict:
    """沉淀一条冲突规则并落盘，返回完整规则对象。"""
    if not isinstance(keyword_cluster, list) or not keyword_cluster:
        raise ValueError("keyword_cluster 必须为非空数组")
    if severity not in ("warning", "info"):
        severity = "warning"
    rules = load_custom_rules()
    rid = next_conflict_id()
    if not rule:
        kc = "、".join(str(k) for k in keyword_cluster)
        rule = f"多个技能 description 不应同时高频包含 {{{kc}}}，须差异化定位或合并。"
    obj = {
        "id": rid,
        "dim": "冲突",
        "keyword_cluster": [str(k) for k in keyword_cluster],
        "rule": rule,
        "severity": severity,
        "source": "conflict-detector",
    }
    rules.append(obj)
    CUSTOM_RULES_PATH.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return obj
