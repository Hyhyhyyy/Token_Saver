"""SkillForge 技能资产标准规范 v1.0（程序内定义，供校验/清洗/前端展示共用）。"""
from __future__ import annotations

from .config import DESC_TARGET_TOKENS, DESC_HARD_TOKENS

STANDARD_VERSION = "1.0.0"

# 标准 SKILL.md 模板（用户可视化的"目标形态"）
SKILL_TEMPLATE = """---
name: <skill-id>            # 必须：kebab-case，与目录名一致
description: <用途一句话>。触发场景：<场景1>；<场景2>；<场景3>。
---

# <技能标题>

<正文：仅保留核心流程与资源引用，细节放入 references/，模板放入 assets/>
"""

# description 推荐模板与示例
DESC_TEMPLATE = "<用途一句话>。触发场景：<场景1>；<场景2>；<场景3>。"
DESC_EXAMPLE = "将本地 Office/WPS 文档实时读写为可编辑内容。触发场景：用户要打开/编辑 docx、xlsx、pptx 等本地文件；需要所见即所得地修改并保存。"

# 校验规则说明（前端展示用）
VALIDATION_RULES = [
    {
        "id": "FORMAT-01",
        "dim": "格式",
        "field": "name",
        "rule": "name 必填，且为 kebab-case（小写字母/数字/连字符），长度 1-48，与目录名一致。",
        "severity": "error",
    },
    {
        "id": "FORMAT-02",
        "dim": "格式",
        "field": "frontmatter",
        "rule": "YAML frontmatter 必须存在且可解析，至少包含 name 与 description。",
        "severity": "error",
    },
    {
        "id": "SEMANTIC-01",
        "dim": "语义",
        "field": "description",
        "rule": "description 必须包含明确的用途陈述与触发场景（含'触发场景：'或等价表述）。",
        "severity": "error",
    },
    {
        "id": "SEMANTIC-02",
        "dim": "语义",
        "field": "description",
        "rule": "description 应聚焦单一职责，避免并列多个无关能力（'还能做 X'）。",
        "severity": "warning",
    },
    {
        "id": "REDUNDANT-01",
        "dim": "冗余",
        "field": "description",
        # 口径统一（PRD Q5）：动态读取 config 真实常量，消除与 40/90 硬编码不一致
        "rule": f"description Token 数应 ≤ {DESC_HARD_TOKENS}（目标 ≤ {DESC_TARGET_TOKENS}），超预算触发压缩。",
        "severity": "warning",
    },
    {
        "id": "REDUNDANT-02",
        "dim": "冗余",
        "field": "frontmatter",
        "rule": "不得存在 description/description_zh/description_en 等重复语义字段；保留单一 description。",
        "severity": "warning",
    },
    {
        "id": "REDUNDANT-03",
        "dim": "冗余",
        "field": "description",
        "rule": "不得包含营销废话（强大的/一站式/极致/seamless 等）与重复短语。",
        "severity": "warning",
    },
    {
        "id": "REDUNDANT-04",
        "dim": "冗余",
        "field": "body",
        "rule": "SKILL.md 正文应精简；>10k 字的细节应移入 references/，模板放入 assets/。",
        "severity": "info",
    },
]

# 健康度评分权重
HEALTH_WEIGHTS = {
    "format_error": 30,
    "semantic_error": 30,
    "redundancy": 40,
}


def get_validation_rules() -> list[dict]:
    """合并内置规则与自定义规则（来自 custom_rules.json），自定义项标注 source=custom。

    供 GET /api/spec 与 validator 使用，使沉淀的冲突规则即时生效且可审计。
    """
    from .custom_rules import load_custom_rules

    rules: list[dict] = [dict(r) for r in VALIDATION_RULES]
    for r in load_custom_rules():
        merged = dict(r)
        merged["source"] = "custom"
        rules.append(merged)
    return rules
