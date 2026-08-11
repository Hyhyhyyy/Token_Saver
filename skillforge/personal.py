"""个性化口癖管理（零新增依赖：仅标准库 json）。

用户把自己常写、但白费 token 的口癖（如「请」「麻烦你」）写入清单，
简化（Prompt 简化器）时默认消除。数据落 DATA_DIR/personal_phrases.json，
与其它运行时数据一致（gitignored）。
"""
from __future__ import annotations

import json

from . import config


def load_personal_phrases() -> list[str]:
    """读取个性化口癖清单；文件缺失/损坏一律回退空列表，绝不抛异常。"""
    try:
        if config.PERSONAL_PHRASES_PATH.exists():
            data = json.loads(config.PERSONAL_PHRASES_PATH.read_text(encoding="utf-8"))
            return [str(p) for p in data.get("phrases", []) if p]
    except Exception:
        pass
    return []


def _save(phrases: list[str]) -> None:
    config.PERSONAL_PHRASES_PATH.write_text(
        json.dumps({"phrases": phrases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_personal_phrase(phrase: str) -> tuple[list[str], bool]:
    """新增一条口癖（自动 trim、去重）。返回 (最新清单, 是否实际新增)。"""
    phrase = (phrase or "").strip()
    phrases = load_personal_phrases()
    if not phrase or phrase in phrases:
        return phrases, False
    phrases.append(phrase)
    _save(phrases)
    return phrases, True


def remove_personal_phrase(phrase: str) -> list[str]:
    """删除一条口癖（按精确匹配）。返回最新清单。"""
    phrase = (phrase or "").strip()
    phrases = load_personal_phrases()
    if phrase in phrases:
        phrases.remove(phrase)
        _save(phrases)
    return phrases


def set_phrases(phrases: list[str]) -> list[str]:
    """整体替换清单（去空白/去重/保序）。返回最新清单。"""
    seen = set()
    out = []
    for p in phrases or []:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    _save(out)
    return out
