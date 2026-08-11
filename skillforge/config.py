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
# 个性化口癖清单（用户自定义的常写、白费 token 的短语；简化时默认消除）
PERSONAL_PHRASES_PATH = DATA_DIR / "personal_phrases.json"

# 语义冲突检测阈值（UI slider 0.5–0.95，默认 0.7）
CONFLICT_DEFAULT_THRESHOLD = 0.7          # local-tfidf 档（v2.1 沿用）
CONFLICT_THRESHOLD_MIN = 0.5
CONFLICT_THRESHOLD_MAX = 0.95

# embedding 档阈值（A-2：稠密向量余弦尺度，阈值随后端分档）
CONFLICT_DEFAULT_THRESHOLD_EMBEDDING = 0.55
CONFLICT_AUTO_DEPOSIT_THRESHOLD_EMBEDDING = 0.85

# 本地 embedding 服务默认端点（local-st provider 指向本地 OpenAI 兼容服务，零新增依赖）
EMBEDDING_API_URL = os.environ.get(
    "EMBEDDING_API_URL", "http://localhost:11434/v1/embeddings"
)

# 自进化自动循环（B-1/B-2）：默认关，绝不静默写盘
EVOLVE_INTERVAL_MINUTES = int(os.environ.get("EVOLVE_INTERVAL_MINUTES", "30"))

# 预算回调（自进化闭环）：回归累计≥TRIGGER 次自动回调一档 STEP，封顶 DESC_HARD_TOKENS
BUDGET_RECALL_STEP = 20
BUDGET_RECALL_TRIGGER = 2

# 定价快照日期（仅供仿真参考，实际以厂商官方为准）
PRICING_AS_OF = "2025-09"

# ---- 自进化 v2.1 增量配置（GOAL-1 真实信号 / GOAL-2 自主运行 / GOAL-3 可追溯）----
# 用户真实技能目录（gold 自动播种扫描目标）。可用环境变量覆盖，默认 ~/.workbuddy/skills。
USER_SKILLS_DIR = Path(
    os.environ.get("USER_SKILLS_DIR", str(Path(os.path.expanduser("~/.workbuddy/skills"))))
)

# gold 样本数 < 此值则 run_evolve / bootstrap 自动播种真实技能信号
GOLD_SEED_THRESHOLD = 3
# F3 语义相似度 ≥ 此值，run_evolve 自动沉淀冲突规则（P0）
CONFLICT_AUTO_DEPOSIT_THRESHOLD = 0.9
# 校准采样技能对数（取 local-tfidf 相似度最高的前 N 对）
CALIBRATION_SAMPLE_PAIRS = 30
# F1 回归技能的「规则自动沉淀」开关（P1，默认关闭，避免噪声规则）
EVOLVE_AUTO_DEPOSIT_F1_RULE = False

# ---- v2.3 增量配置（A-1 / A-2 / A-3 / B-2 / C-2 / C-4 / D-1 / D-2）----
# 全部读环境变量、带默认值；保持与 arch §7.1 命名一致。

# A-3 低水位：gold 覆盖度 < 此值则 run_evolve 主动再播种（自愈停滞）
GOLD_COVERAGE_LOW_WATERMARK = float(os.environ.get("GOLD_COVERAGE_LOW_WATERMARK", "80"))

# B-2 趋势图异常高亮阈值
ANOMALY_F1_DROP = float(os.environ.get("ANOMALY_F1_DROP", "0.1"))   # f1_acc_after 降幅
ANOMALY_COV_DROP = float(os.environ.get("ANOMALY_COV_DROP", "5"))    # gold_coverage 下降百分点

# C-2 / C-4 跨进程文件锁（仅包裹 run_evolve 整体）
FILELOCK_TIMEOUT_SEC = float(os.environ.get("FILELOCK_TIMEOUT_SEC", "5"))
LOCK_PATH = DATA_DIR / ".skillforge.lock"

# A-1 技能内容签名存储（sha256 映射）
SKILLS_SIGNATURE_PATH = DATA_DIR / "skills_signature.json"

# D-1 本地后端预设模板（仓库内置，首次启动复制为 DATA_DIR/vectorizer.json）
VECTORIZER_PRESET_ST_PATH = Path(__file__).resolve().parent.parent / "data" / "vectorizer.local-st.json"

# D-2 ollama 探测端点（默认同 EMBEDDING_API_URL）
EMBEDDING_PROBE_URL = os.environ.get("EMBEDDING_PROBE_URL", EMBEDDING_API_URL)

# ---- v2.4 增量配置（A-5 节流 / D-3 多本地候选探测）----

# A-5 heartbeat 节流：连续 no-op 且指标值与上一行相同、且距上一行写入 < 该间隔（秒）
# 时跳过本行 metrics 写入（抽稀，避免长空转膨胀），值变 / 超间隔必写保证趋势连续。
HEARTBEAT_MIN_INTERVAL_SEC = float(os.environ.get("HEARTBEAT_MIN_INTERVAL_SEC", "60"))

# D-3 多本地后端候选探测：逗号分隔的 OpenAI 兼容 embeddings 端点列表，默认含 ollama。
# 启动 / 显式刷新时按序探测首个可用者落地 local-st（provider=local-st）。
EMBEDDING_CANDIDATE_URLS = [
    u.strip()
    for u in os.environ.get(
        "EMBEDDING_CANDIDATE_URLS", "http://localhost:11434/v1/embeddings"
    ).split(",")
    if u.strip()
]


def auto_evolve_on_start() -> bool:
    """开机自启开关：读取 AUTO_EVOLVE_ON_START 环境变量（默认 false）。

    每次调用求值、不缓存，避免进程期内环境变量变更被忽略。
    """
    return os.environ.get("AUTO_EVOLVE_ON_START", "false").lower() == "true"


def auto_evolve_loop() -> bool:
    """后台周期自动循环总开关：读取 AUTO_EVOLVE_LOOP 环境变量（默认 false）。

    每次调用求值、不缓存，避免进程期内环境变量变更被忽略。
    """
    return os.environ.get("AUTO_EVOLVE_LOOP", "false").lower() == "true"
