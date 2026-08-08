"""技能内容签名侦测（A-1 · 进化压力源）。

对 USER_SKILLS_DIR 下每个已装技能的 SKILL.md 计算 sha256 内容签名，存于
DATA_DIR/skills_signature.json。run_evolve 进入时比对当前签名与已存签名，得到
changeset（added / removed / changed）；非空则视为外部技能集变化，触发再播种 +
写 skill_signature_change 账本条目（详见 arch §7.2）。

设计约束（零新增依赖）：仅用 Python 标准库（hashlib / json / pathlib）。
默认算法 sha256 文件内容（Q4 默认）；mtime 低成本模式为 P1，不影响 P0。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config


def compute_signatures(skills_dir: Path | None = None) -> dict[str, str]:
    """对 USER_SKILLS_DIR 每个含 SKILL.md 的技能子目录算 sha256 内容签名。

    返回 {技能名: hex}（技能名 = 子目录名）。缺省目录不存在时返回空 dict。
    """
    skills_dir = Path(skills_dir) if skills_dir is not None else config.USER_SKILLS_DIR
    sigs: dict[str, str] = {}
    if not skills_dir.exists() or not skills_dir.is_dir():
        return sigs
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_bytes()
        except OSError:
            continue
        sigs[d.name] = hashlib.sha256(content).hexdigest()
    return sigs


def load_saved_signatures(path: Path | None = None) -> dict[str, str]:
    """读取 DATA_DIR/skills_signature.json；不存在或非法返回 {}。"""
    path = Path(path) if path is not None else config.SKILLS_SIGNATURE_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def compare_signatures(current: dict[str, str], saved: dict[str, str]) -> dict:
    """比对当前与已存签名，返回 {added, removed, changed}（均为名称列表）。"""
    added = [k for k in current if k not in saved]
    removed = [k for k in saved if k not in current]
    changed = [k for k in current if k in saved and current[k] != saved[k]]
    return {"added": added, "removed": removed, "changed": changed}


def save_signatures(sigs: dict[str, str], path: Path | None = None) -> None:
    """写 DATA_DIR/skills_signature.json（幂等：覆盖写入当前全量签名）。"""
    path = Path(path) if path is not None else config.SKILLS_SIGNATURE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sigs, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_external_change(skills_dir: Path | None = None,
                           path: Path | None = None) -> tuple[dict, bool]:
    """计算当前签名并与已存签名比对，返回 (changeset, external_change)。

    external_change 仅在「存在历史基线」且 changeset 非空时为真——首次运行仅建立
    基线（写入基线但不记 skill_signature_change，避免把初始播种误报为外部变化）。
    """
    current = compute_signatures(skills_dir)
    saved = load_saved_signatures(path)
    changeset = compare_signatures(current, saved)
    external_change = bool(saved) and any(
        changeset["added"] or changeset["removed"] or changeset["changed"]
    )
    return changeset, external_change
