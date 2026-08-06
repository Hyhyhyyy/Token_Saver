"""格式校验：对解析后的技能按标准规范产出问题列表与健康度评分。"""
from __future__ import annotations

import re

from .config import ALLOWED_FRONTMATTER_FIELDS, DESC_HARD_TOKENS, DESC_TARGET_TOKENS, FILLER_WORDS
from .spec import HEALTH_WEIGHTS

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _is_third_person_or_imperative(desc: str) -> bool:
    # 中文：含"当用户/当...时/用于/适用于"或"使用本技能/执行"等；英文 third-person
    return bool(re.search(r"(当用户|当.*时|用于|适用于|本技能|Use this skill|This skill|Guid|Guide)", desc))


def validate(parsed: dict, custom_rules: list | None = None) -> dict:
    issues = []
    fm = parsed.get("frontmatter", {}) or {}
    name = fm.get("name")
    dir_name = parsed.get("dir_name", "")
    desc = (fm.get("description") or "").strip()
    body = parsed.get("body", "") or ""

    if parsed.get("parse_error"):
        issues.append(_issue("FORMAT-02", "error", "frontmatter", parsed["parse_error"], "补充标准 YAML frontmatter。"))

    # FORMAT-01 name
    if not name:
        issues.append(_issue("FORMAT-01", "error", "name", "缺少 name 字段。", "在 frontmatter 中添加 name: <skill-id>。"))
    else:
        if not _KEBAB_RE.match(str(name)):
            issues.append(_issue("FORMAT-01", "error", "name",
                                 f"name '{name}' 不符合 kebab-case（小写字母/数字/连字符）。",
                                 "改为小写中划线命名，如 my-skill。"))
        if dir_name and str(name) != dir_name:
            issues.append(_issue("FORMAT-01", "error", "name",
                                 f"name '{name}' 与目录名 '{dir_name}' 不一致。",
                                 "使二者保持一致，Agent 据此定位技能。"))

    # SEMANTIC-01 description 必备
    if not desc:
        issues.append(_issue("SEMANTIC-01", "error", "description", "缺少 description 字段。",
                             "按模板填写用途与触发场景。"))
    else:
        if not _is_third_person_or_imperative(desc):
            issues.append(_issue("SEMANTIC-01", "warning", "description",
                                 "description 未体现明确的触发语义（建议含'触发场景：'或等价表述）。",
                                 "采用标准模板：<用途>。触发场景：<a>；<b>；<c>。"))

        # SEMANTIC-02 单职责
        if re.search(r"(还能|并且|以及.*还能|also|additionally|and can also)", desc):
            issues.append(_issue("SEMANTIC-02", "warning", "description",
                                 "description 疑似并列多个无关能力，可能稀释调度准确性。",
                                 "聚焦单一职责，拆分为多个技能或在正文展开。"))

        # REDUNDANT-01 token 预算
        tokens = parsed.get("desc_tokens", 0)
        if tokens > DESC_HARD_TOKENS:
            issues.append(_issue("REDUNDANT-01", "warning", "description",
                                 f"description 共 {tokens} token（硬上限 {DESC_HARD_TOKENS}，目标 {DESC_TARGET_TOKENS}）。",
                                 "执行清洗压缩至目标预算内。"))
        elif tokens > DESC_TARGET_TOKENS:
            issues.append(_issue("REDUNDANT-01", "info", "description",
                                 f"description 共 {tokens} token（目标 ≤ {DESC_TARGET_TOKENS}），仍有压缩空间。",
                                 "可进一步优化措辞。"))

        # REDUNDANT-03 营销废话
        hits = [w for w in FILLER_WORDS if w in desc]
        if hits:
            issues.append(_issue("REDUNDANT-03", "warning", "description",
                                 f"description 含冗余/营销词：{', '.join(hits)}。",
                                 "删除填充词，保留事实性描述。"))

        # 重复短语检测
        dups = _find_repeated_phrases(desc)
        if dups:
            issues.append(_issue("REDUNDANT-03", "warning", "description",
                                 f"description 存在重复短语：{', '.join(dups)}。",
                                 "合并重复表述。"))

    # REDUNDANT-02 重复语义字段
    dup_fields = [k for k in fm if re.match(r"^description(_zh|_en|_cn)?$", str(k)) and k != "description"]
    if dup_fields:
        issues.append(_issue("REDUNDANT-02", "warning", "frontmatter",
                             f"存在重复语义字段：{', '.join(dup_fields)}。",
                             "仅保留单一 description，其余翻译/扩展放入正文或 references/。"))

    # 多余字段（严格模式可选，这里仅 info）
    extra = [k for k in fm if k not in ALLOWED_FRONTMATTER_FIELDS]
    if extra:
        issues.append(_issue("FORMAT-02", "info", "frontmatter",
                             f"含非标准字段：{', '.join(map(str, extra))}。",
                             "如不影响调度可保留；如需极致精简可移除非必要字段。"))

    # REDUNDANT-04 正文精简
    if len(body) > 10000:
        issues.append(_issue("REDUNDANT-04", "info", "body",
                             f"正文约 {len(body)} 字，建议将细节移入 references/。",
                             "拆分到 references/ 降低常驻上下文。"))

    # 自定义冲突规则（灰度可控：仅当传入 custom_rules 时生效）
    # dim=="冲突" 规则检查 keyword_cluster 是否出现在 description，命中产出 warning/info
    if custom_rules:
        for r in custom_rules:
            if r.get("dim") != "冲突":
                continue
            kc = r.get("keyword_cluster") or []
            if any(str(k) in desc for k in kc):
                issues.append(_issue(
                    r.get("id", "CONFLICT"),
                    r.get("severity", "warning"),
                    "description",
                    f"description 与关键词簇 {kc} 高度重叠，可能与其他技能冲突。",
                    r.get("rule", "建议差异化定位或合并冲突技能。"),
                ))

    score = _score(issues)
    desc_tokens = parsed.get("desc_tokens", 0)
    status = "invalid" if score < 60 else ("warning" if score < 90 else "valid")
    # 描述超硬上限不应评为"合规"（即便其它维度满分）
    if desc_tokens > DESC_HARD_TOKENS and status == "valid":
        status = "warning"
    return {
        "name": name or dir_name,
        "issues": issues,
        "score": score,
        "error_count": sum(1 for i in issues if i["severity"] == "error"),
        "warning_count": sum(1 for i in issues if i["severity"] == "warning"),
        "info_count": sum(1 for i in issues if i["severity"] == "info"),
        "status": status,
    }


def _issue(rule_id, severity, field, message, suggestion):
    return {"code": rule_id, "severity": severity, "field": field,
            "message": message, "suggestion": suggestion}


def _find_repeated_phrases(text: str, min_len: int = 4):
    # 基于 2-gram 中文/英文片段的简易重复检测
    phrases = set()
    dups = set()
    # 中文字符 n-gram
    cjk = re.findall(r"[一-鿿]{4,}", text)
    for w in cjk:
        for n in (4, 5):
            for i in range(0, len(w) - n + 1, n):
                seg = w[i:i + n]
                if seg in phrases:
                    dups.add(seg)
                else:
                    phrases.add(seg)
    return list(dups)[:5]


def _score(issues) -> int:
    errors = sum(1 for i in issues if i["severity"] == "error")
    warns = sum(1 for i in issues if i["severity"] == "warning")
    infos = sum(1 for i in issues if i["severity"] == "info")
    penalty = errors * 18 + warns * 6 + infos * 2
    return max(0, 100 - penalty)
