"""配置：技能扫描目录、数据存储目录、可调参数。"""
from __future__ import annotations

import os
from pathlib import Path

# 默认扫描目录：用户级 skills + 项目级 skills（可在环境变量覆盖）
_DEFAULT_USER_SKILLS = Path(os.path.expanduser("~/.workbuddy/skills"))
_DEFAULT_PROJECT_SKILLS = Path(os.getcwd()) / ".workbuddy" / "skills"


def _resolve_skills_dirs() -> list[Path]:
    env = os.environ.get("SKILLS_DIRS")
    if env:
        raw = [p.strip() for p in env.replace(";", ":").split(":") if p.strip()]
        return [Path(p).expanduser() for p in raw]
    dirs = []
    for d in (_DEFAULT_USER_SKILLS, _DEFAULT_PROJECT_SKILLS):
        if d.exists():
            dirs.append(d)
    # 兜底：当前工作区下常见的 skills 位置
    return dirs or [_DEFAULT_USER_SKILLS]


SKILLS_DIRS: list[Path] = _resolve_skills_dirs()

DATA_DIR: Path = Path(os.environ.get("DATA_DIR", Path(os.getcwd()) / "data")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH: Path = DATA_DIR / "skillforge.db"

# 描述 Token 预算（cl100k_base 估算），超出即触发压缩建议
# 目标：在保留「用途 + 触发场景」的前提下尽量精简；硬上限为可接受上界
DESC_TARGET_TOKENS = 60
DESC_HARD_TOKENS = 120

# 清洗时可保留的"非标准但常见"前置字段（其余多余字段在严格模式下移除）
ALLOWED_FRONTMATTER_FIELDS = {
    "name",
    "description",
    "agent_created",
    "version",
    "license",
    "author",
    "allowed-tools",
    "disable",
}

# 被视为"冗余/营销废话"的中英文填充词，清洗阶段移除
FILLER_WORDS = [
    "强大的", "一站式", "极致", "高效", "轻松", "智能地", "完美", "全面",
    "专业的", "便捷的", "快速的", "自动", "非常好", "极其",
    "powerful", "seamless", "ultimate", "best-in-class", "smart", "easy",
    "just", "simply", "very", "really", "amazing",
]

# ---- 自进化增量（F1/F2/F3）配置 ----
# 所有运行时可编辑配置统一落 DATA_DIR，文件优先、缺失回退内置默认（开箱即跑）
GOLD_PATH = DATA_DIR / "gold_samples.json"
PRICING_PATH = DATA_DIR / "pricing.json"
VECTORIZER_PATH = DATA_DIR / "vectorizer.json"
BUDGET_OVERRIDES_PATH = DATA_DIR / "skill_budget_overrides.json"
CUSTOM_RULES_PATH = DATA_DIR / "custom_rules.json"

# 语义冲突检测阈值（UI slider 0.5–0.95，默认 0.7）
CONFLICT_DEFAULT_THRESHOLD = 0.7
CONFLICT_THRESHOLD_MIN = 0.5
CONFLICT_THRESHOLD_MAX = 0.95

# 预算回调（自进化闭环）：回归累计≥TRIGGER 次自动回调一档 STEP，封顶 DESC_HARD_TOKENS
BUDGET_RECALL_STEP = 20
BUDGET_RECALL_TRIGGER = 2

# 定价快照日期（仅供仿真参考，实际以厂商官方为准）
PRICING_AS_OF = "2025-09"
