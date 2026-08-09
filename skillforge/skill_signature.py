"""技能内容签名侦测（A-1 · 进化压力源）。

对 USER_SKILLS_DIR 下每个已装技能目录计算「全目录复合指纹」：

  - 递归列出该技能目录下所有文件（相对路径，即清单 manifest）；
  - 对关键文本/配置文件（SKILL.md、scripts/、references/、*.json/*.yaml/*.yml/*.md
    等）取其内容 sha256；
  - 对所有文件取其 mtime；
  - 组合（清单 + 关键内容哈希 + 全 mtime）求单值 sha256 hex 作为该技能指纹。

大二进制仅纳入清单 + mtime，不参与内容哈希（避免无意义 IO）。

返回 `{技能名: hex}`（技能名 = 子目录名），维持与 v2.3 相同的外层结构。

R-1 兼容性（v2.4 基线静默迁移）：
  - 存储格式新增元字段 `_schema`（= SIGNATURE_SCHEMA）。
  - `load_saved_signatures` 在读到的 `_schema` 缺失或不等于 `SIGNATURE_SCHEMA` 时返回
    `{}`，视为「无基线」；`detect_external_change` 据此 `external_change=False`，不写
    `skill_signature_change` 账本——避免升级首跑因旧 SKILL.md-only 指纹格式不同而误报。

设计约束（零新增依赖）：仅用 Python 标准库（hashlib / json / os / pathlib）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import config

# 复合指纹 schema 版本（v2.4 起）。旧 v2.3 仅扫 SKILL.md 内容、且无 _schema 字段。
SIGNATURE_SCHEMA: int = 2

# 关键文本/配置文件后缀（参与内容哈希）
_KEY_TEXT_SUFFIXES = (
    ".md", ".markdown", ".json", ".yaml", ".yml", ".txt", ".toml", ".cfg",
    ".ini", ".csv", ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bat",
    ".ps1", ".xml", ".html", ".css", ".lock", ".env",
)

# 关键目录前缀（其下文件一律参与内容哈希，覆盖 scripts/references/assets/prompts 等）
_KEY_DIR_PREFIXES = ("scripts", "references", "assets", "prompts", "examples")


def _is_key_text(rel: Path) -> bool:
    """相对路径文件是否参与内容哈希（关键文本/配置）。

    满足以下任一即视为关键文件：
      - 后缀在 _KEY_TEXT_SUFFIXES；
      - 路径中（跳过技能目录名）含 _KEY_DIR_PREFIXES 中的目录段（如 scripts/）。
    """
    if rel.suffix.lower() in _KEY_TEXT_SUFFIXES:
        return True
    for part in rel.parts[1:]:  # 跳过技能目录名本身
        if part in _KEY_DIR_PREFIXES:
            return True
    return False


def _compute_one_signature(skill_dir: Path, files: list[Path]) -> str:
    """对单个技能目录计算复合指纹（单值 64 位 hex）。

    组成（确定性、UTF-8）：
      MANIFEST  -> 全部文件相对路径排序清单
      CONTENT   -> 关键文件（相对路径:内容sha256）
      MTIME     -> 全部文件（相对路径:mtime，保留 6 位小数）
    大二进制仅入清单 + mtime，不参与内容哈希。
    """
    h = hashlib.sha256()
    rel_paths = sorted(str(f.relative_to(skill_dir)) for f in files)

    # 1) 文件清单（相对路径，排序）
    h.update(b"MANIFEST\x00")
    h.update("\n".join(rel_paths).encode("utf-8"))
    h.update(b"\x00")

    # 2) 关键文本/配置文件内容哈希（按相对路径排序，保证确定性）
    h.update(b"CONTENT\x00")
    for rel in rel_paths:
        fp = skill_dir / rel
        if not _is_key_text(Path(rel)):
            continue
        try:
            content = fp.read_bytes()
        except OSError:
            content = b""
        h.update(rel.encode("utf-8"))
        h.update(b":")
        h.update(hashlib.sha256(content).digest())
        h.update(b"\n")

    # 3) 全部文件 mtime（按相对路径排序）
    h.update(b"MTIME\x00")
    for rel in rel_paths:
        fp = skill_dir / rel
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            mtime = 0.0
        h.update(rel.encode("utf-8"))
        h.update(b":")
        h.update(f"{mtime:.6f}".encode("utf-8"))
        h.update(b"\n")

    return h.hexdigest()


def compute_signatures(skills_dir: Path | None = None) -> dict[str, str]:
    """全目录复合指纹：对 USER_SKILLS_DIR 每个技能子目录算单值 hex。

    返回 {技能名: hex}（技能名 = 子目录名）。缺省目录不存在时返回空 dict。

    任被追踪文件（含新增大文件、改 scripts/references/ 下任意文件、改 mtime）增删改，
    均使该技能指纹变化，下一轮 detect_external_change 触发再进化 + 写账本。
    """
    skills_dir = Path(skills_dir) if skills_dir is not None else config.USER_SKILLS_DIR
    sigs: dict[str, str] = {}
    if not skills_dir.exists() or not skills_dir.is_dir():
        return sigs
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        files = [f for f in d.rglob("*") if f.is_file()]
        if not files:
            continue
        sigs[d.name] = _compute_one_signature(d, files)
    return sigs


def load_saved_signatures(path: Path | None = None) -> dict[str, str]:
    """读取 DATA_DIR/skills_signature.json；R-1 schema 不符或非法返回 {}（静默重建）。

    仅当文件存在、为 dict、且 `_schema == SIGNATURE_SCHEMA` 时才返回 {技能名: hex}
    （剥离 `_schema` 元字段）；否则返回 {} —— 视为无基线，触发静默重建、不误报。
    """
    path = Path(path) if path is not None else config.SKILLS_SIGNATURE_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # R-1 基线迁移：schema 不符（缺失 / 旧 v2.3 SKILL.md-only hex）→ 视为无基线
        if data.get("_schema") != SIGNATURE_SCHEMA:
            return {}
        return {str(k): str(v) for k, v in data.items() if k != "_schema"}
    except Exception:
        return {}


def compare_signatures(current: dict[str, str], saved: dict[str, str]) -> dict:
    """比对当前与已存签名，返回 {added, removed, changed}（均为名称列表）。"""
    added = [k for k in current if k not in saved]
    removed = [k for k in saved if k not in current]
    changed = [k for k in current if k in saved and current[k] != saved[k]]
    return {"added": added, "removed": removed, "changed": changed}


def save_signatures(sigs: dict[str, str], path: Path | None = None) -> None:
    """写 DATA_DIR/skills_signature.json（幂等：覆盖写入当前全量签名 + _schema 元字段）。"""
    path = Path(path) if path is not None else config.SKILLS_SIGNATURE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {**sigs, "_schema": SIGNATURE_SCHEMA}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_external_change(skills_dir: Path | None = None,
                           path: Path | None = None) -> tuple[dict, bool]:
    """计算当前签名并与已存签名比对，返回 (changeset, external_change)。

    external_change 仅在「存在历史基线（_schema 相符）」且 changeset 非空时为真。
    首次运行 / 升级首跑（_schema 不符）仅建立基线（写入基线但不记
    skill_signature_change，避免把初始播种/基线迁移误报为外部变化）。
    """
    current = compute_signatures(skills_dir)
    saved = load_saved_signatures(path)
    changeset = compare_signatures(current, saved)
    external_change = bool(saved) and any(
        changeset["added"] or changeset["removed"] or changeset["changed"]
    )
    return changeset, external_change
