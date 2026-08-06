"""语义清洗 + 冗余压缩引擎。

两阶段：
  Stage 1（规则，确定性、无需 LLM）：字段归一、填充词移除、触发场景标准化、重复字段合并。
  Stage 2（可选 LLM）：在配置了 LLM_API_URL/KEY 时做语义级重写，进一步压到目标 Token 预算。
"""
from __future__ import annotations

import os
import re
import urllib.request
import json

import yaml

from .config import ALLOWED_FRONTMATTER_FIELDS, DESC_TARGET_TOKENS, FILLER_WORDS
from .tokenizer import count_tokens

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRIGGER_KW = re.compile(r"(触发场景\s*[:：]|触发\s*[:：]|适用场景\s*[:：]|使用场景\s*[:：])")
_FEATURE_KW = re.compile(r"(支持|提供|包括|涵盖|包含|具备|可完成|能)")
_SEP = re.compile(r"[；;，,、+/]+")


def _normalize_name(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _strip_filler(text: str) -> str:
    for w in FILLER_WORDS:
        text = text.replace(w, "")
    # 折叠多余空格/标点
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"([。；;])\1+", r"\1", text)
    return text.strip()


def _split_triggers(part: str, max_items: int = 3, max_len: int = 18) -> list[str]:
    raw = [t.strip(" ；;，,。") for t in _SEP.split(part)]
    out = []
    seen = set()
    for t in raw:
        if not t:
            continue
        # 去掉 "适用于/用于" 等前缀与括号内示例，保留核心场景词
        t = re.sub(r"^(适用于|用于|适合|针对|包含|包括|提供|支持)", "", t)
        t = re.sub(r"[（(].*?[)）]", "", t)
        t = t.strip(" ：:，。；;")
        if not t or t in seen:
            continue
        # 丢弃残缺/噪声片段（"等…场景"、未闭合括号、以"的/场景"结尾、单字母档位残留）
        if any(bad in t for bad in ("等", "场景", "（", "(", "的")):
            continue
        if re.fullmatch(r"[A-C](基础|档|完美|兜底|预警)", t):
            continue
        seen.add(t)
        # 过长（通常是"等需要...的场景"这类拖尾）直接丢弃，避免污染触发列表
        if len(t) <= max_len:
            out.append(t)
        if len(out) >= max_items:
            break
    return out


def _clean_purpose(purpose: str) -> str:
    """用途句归一：去前缀词、去括号示例、折叠空白。"""
    purpose = re.sub(r"^(希望|需要|想要|欲|用于|本技能用于)", "", purpose)
    purpose = re.sub(r"[（(].*?[)）]", "", purpose)  # 去掉括号内示例
    purpose = re.sub(r"\s+", "", purpose).strip(" ，。；;：")
    return purpose


def _extract_purpose_triggers(desc: str):
    """从混乱描述中拆出 (purpose, [triggers])，尽量保留触发语义。"""
    desc = _strip_filler(desc)

    # 1) 显式「触发场景：」标记
    m = _TRIGGER_KW.search(desc)
    if m:
        purpose = _clean_purpose(desc[: m.start()])
        triggers = _split_triggers(desc[m.end():])
        return purpose, triggers

    # 2) "当用户X时" / "当用户希望X时，使用本技能" —— 提取 X 作为用途内容
    pm = re.search(r"当用户(.+?)时", desc)
    if pm:
        purpose = _clean_purpose(pm.group(1))
        rest = desc[pm.end():].lstrip(" ，。；;：")
        rest = re.sub(r"^(，使用本技能|使用本技能|本技能用于|，用于|用于)[，。；:：]?", "", rest)
        feat = _FEATURE_KW.search(rest)
        if feat:
            rest = rest[feat.end():]
        triggers = _split_triggers(rest)
        return purpose, triggers

    # 3) "本技能用于X"
    um = re.search(r"本技能用于(.+?)(?:。|$)", desc)
    if um:
        purpose = _clean_purpose(um.group(1))
        rest = desc[um.end():].lstrip(" ，。；;：")
        feat = _FEATURE_KW.search(rest)
        if feat:
            rest = rest[feat.end():]
        triggers = _split_triggers(rest)
        return purpose, triggers

    # 4) 退化：首句用途 + 其余拆为场景
    sentences = [s.strip() for s in re.split(r"[。；;]", desc) if s.strip()]
    if not sentences:
        return desc, []
    return _clean_purpose(sentences[0]), _split_triggers("；".join(sentences[1:]))


def _compress_to_budget(purpose: str, triggers: list[str], target: int) -> tuple[str, list[str]]:
    """在不超过目标 token 的前提下，保留 purpose + 最多若干触发场景。"""
    best = triggers[:]
    while best:
        cand = f"{purpose}。触发场景：{'；'.join(best)}。"
        if count_tokens(cand) <= target:
            return purpose, best
        best = best[:-1]
    # 连单个触发场景都超，则直接截断 purpose 之外的部分
    return purpose, []


def clean_description(desc: str, target: int = DESC_TARGET_TOKENS) -> tuple[str, list[str]]:
    purpose, triggers = _extract_purpose_triggers(desc)
    if not purpose:
        purpose = (desc or "").strip()[:40]
    purpose, triggers = _compress_to_budget(purpose, triggers, target)
    cleaned = f"{purpose}。触发场景：{'；'.join(triggers)}。" if triggers else f"{purpose}。"
    return cleaned, triggers


def _call_llm(rewrite_prompt: str) -> str | None:
    url = os.environ.get("LLM_API_URL")
    key = os.environ.get("LLM_API_KEY")
    if not url or not key:
        return None
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": rewrite_prompt}],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def clean_skill(parsed: dict, use_llm: bool = False, target: int = DESC_TARGET_TOKENS) -> dict:
    """对单个技能执行清洗，返回清洗结果与变更说明。"""
    fm = dict(parsed.get("frontmatter", {}) or {})
    body = parsed.get("body", "") or ""
    changes = []
    before_tokens = parsed.get("desc_tokens", 0)
    before_total = parsed.get("total_tokens", 0)

    # 1) 名称归一
    orig_name = fm.get("name")
    if orig_name and not _KEBAB_RE.match(str(orig_name)):
        new_name = _normalize_name(orig_name)
        fm["name"] = new_name
        changes.append(f"name 归一为 kebab-case：{orig_name} → {new_name}")
    elif not orig_name:
        new_name = _normalize_name(parsed.get("dir_name", "unnamed-skill"))
        fm["name"] = new_name
        changes.append(f"补全缺失 name：{new_name}")

    # 2) description 清洗
    desc = (fm.get("description") or "").strip()
    if desc:
        cleaned_desc, triggers = clean_description(desc, target)
        if use_llm:
            llm_desc = _call_llm(
                "将以下技能描述重写为不超过 %d token 的中文标准描述，"
                "格式：<用途一句话>。触发场景：<a>；<b>；<c>。\n原文：%s" % (target, desc)
            )
            if llm_desc:
                cleaned_desc = llm_desc.strip()
                changes.append("LLM 语义重写 description")
        if cleaned_desc != desc:
            fm["description"] = cleaned_desc
            changes.append("description 语义清洗 + 冗余压缩")

        # 3) 移除重复语义字段（description_zh/_en 等）
        dup_fields = [k for k in list(fm) if re.match(r"^description(_zh|_en|_cn)?$", str(k)) and k != "description"]
        for k in dup_fields:
            del fm[k]
            changes.append(f"移除重复语义字段：{k}")

    # 4) 过滤非标准多余字段（仅当明确为冗余展示字段）
    for k in list(fm):
        if str(k).startswith("display_name") or str(k) in ("visibility",):
            # 这些字段无害，但为"极致精简"模式可由用户选择；此处保留但提示
            pass

    # 重新组织 frontmatter 顺序：name, description, 其余保留
    ordered = {}
    for k in ("name", "description"):
        if k in fm:
            ordered[k] = fm[k]
    for k, v in fm.items():
        if k not in ordered:
            ordered[k] = v

    after_tokens = count_tokens(ordered.get("description", "") or "")
    after_total = before_total  # 正文规则模式下不变
    saved = max(0, before_tokens - after_tokens)

    result = {
        "name": ordered.get("name"),
        "frontmatter": ordered,
        "body": body,
        "serialized": serialize_skill(ordered, body),
        "before_desc_tokens": before_tokens,
        "after_desc_tokens": after_tokens,
        "before_total_tokens": before_total,
        "after_total_tokens": after_total,
        "saved_tokens": saved,
        "changes": changes,
        "llm_used": use_llm,
    }
    return result


def serialize_skill(frontmatter: dict, body: str) -> str:
    fm_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{fm_text}---\n{body}".replace("---\n---", "---\n---")  # 保证分隔
