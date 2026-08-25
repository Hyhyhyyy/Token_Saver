"""SKILL.md 解析：拆分 frontmatter / 正文，提取字段，扫描技能目录。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .config import SKILLS_DIRS
from .tokenizer import count_tokens

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class SkillParseError(Exception):
    pass


def parse_skill_file(path: Path) -> dict:
    """解析单个 SKILL.md，返回结构化结果。"""
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 没有 frontmatter，尝试把整个文件当正文
        return {
            "path": str(path),
            "dir_name": path.parent.name,
            "frontmatter": {},
            "frontmatter_raw": "",
            "body": text,
            "body_raw": text,
            "parse_error": "缺少 YAML frontmatter（--- ... ---）",
        }
    fm_raw, body = m.group(1), m.group(2)
    try:
        frontmatter = yaml.safe_load(fm_raw) or {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}
    except yaml.YAMLError:
        return {
            "path": str(path),
            "dir_name": path.parent.name,
            "frontmatter": {},
            "frontmatter_raw": fm_raw,
            "body": body,
            "body_raw": text,
            "parse_error": "YAML frontmatter 解析失败",
        }
    return {
        "path": str(path),
        "dir_name": path.parent.name,
        "frontmatter": frontmatter,
        "frontmatter_raw": fm_raw,
        "body": body,
        "body_raw": text,
        "parse_error": None,
    }


def description_tokens(frontmatter: dict) -> int:
    desc = frontmatter.get("description", "") or ""
    return count_tokens(desc)


def scan_skills(dirs: list | None = None) -> list[dict]:
    """递归扫描技能目录，收集 SKILL.md。

    dirs 为 None 时回退到既有 SKILLS_DIRS 行为（v2.0 不变）；
    bootstrap_gold 传 dirs=[config.USER_SKILLS_DIR] 只扫用户目录（v2.1 增量）。
    """
    bases = dirs if dirs is not None else SKILLS_DIRS
    results = []
    seen = set()
    for base in bases:
        if not base.exists():
            continue
        for p in base.rglob("SKILL.md"):
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            parsed = parse_skill_file(p)
            fm = parsed["frontmatter"]
            parsed["name"] = fm.get("name") or parsed["dir_name"]
            parsed["desc_tokens"] = description_tokens(fm)
            parsed["total_tokens"] = count_tokens(parsed["body_raw"])
            results.append(parsed)
    # 按目录/名称排序
    results.sort(key=lambda r: r["name"])
    return results


def get_skill_by_id(skill_id: str) -> Optional[dict]:
    for s in scan_skills():
        if s["name"] == skill_id or s["dir_name"] == skill_id:
            return s
    return None
