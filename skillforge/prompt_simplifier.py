"""Prompt 简化器（v2.6 重构）：通用 prompt 文本压缩 + 可多选规则配置。

目标：在不破坏语义与代码结构的前提下，按用户勾选的「规则类别」做无损裁剪。
保留 v2.5 的全部保护能力（代码块 / 行内代码 / URL / 含「请」安全词冻结）。

设计（见 docs/arch-evo2-6.md）：
- 规则注册表 ``RULE_REGISTRY`` + 预设 ``PRESETS`` + 单一真源 ``ALL_RULE_IDS``。
- ``simplify_prompt(text, mode, rules)`` 改为管道：解析 rules/预设 → 保护 →
  按 ``CANONICAL_ORDER`` 顺序执行启用类别 → 还原 → 统计。
- **零回归硬指标**：``rules is None`` 时 ``PRESETS`` 逐字等于 v2.5 行为
  （balanced/aggressive 输出与旧版字符串相等）。新类别（meta_comment / hedging /
  redundant_adverbs / examples_trim / logical_connector / filler_particles /
  condition_clause / redundant_enum / semantic_compress）仅当用户显式勾选
  （下发 ``rules``）时生效，不进 ``PRESETS``，故老 API 调用方行为不变。

零新增 pip 依赖：仅 Python 标准库 + 现有 tokenizer。

evo2-7 增量实现说明（常量位置 / 局部哨兵约定）：
- 所有词表集中在模块级：``_LOGICAL_CONNECTORS``（排除已属 ``_META_COMMENT`` 的成员，
  避免重复计数）、``_FILLER_PARTICLES``（不含「吗」）、``_CN_FILLERS_EXPANDED``
  （仅 ``explicit=True`` 叠加到 politeness）、``_HEDGING``（已追加多字安全词）、
  ``_CONDITIONAL_MARKERS``（硬排除，仅作文档/防护参考，永不进入连接词）、
  ``_SEQUENCE_CONNECTORS``、``_ORDERED_LIST_LINE_RE``。
- 保护占位符命名空间：外层（跨规则共享）用 ``\\x00P<n>\\x00``（代码/URL/行内代码）与
  ``\\x00K<n>\\x00``（安全词），由 ``_protect/_protect_words/_restore`` 维护；
  规则内局部哨兵用 ``\\x01K<n>\\x01``（如有序列表序列词保护），与外层 ``\\x00`` 隔离，
  不污染 ``_restore``、不被重复计数。
- ``explicit`` 语义：``explicit = (rules is not None)``，仅此标志控制「扩展词表叠加 /
  单字「请」移除 / 新类别生效」；``rules=None`` 永远等价 v2.5。
- ``_tag(change, category, explicit)`` 仅在 ``explicit=True`` 时附加 ``[category]``，
  保障 ``rules=None`` 纯文本格式（parity 关键）。
"""
from __future__ import annotations

import re
import math

from .tokenizer import count_tokens

# --------------------------------------------------------------------------- #
# 规则 id 单一真源（导出，前端 checkbox 与之严格对应）
# --------------------------------------------------------------------------- #
ALL_RULE_IDS: list[str] = [
    "politeness", "first_person", "courtesy_boilerplate", "role_prefix", "empty_items", "duplicate_lines",
    "duplicate_clauses", "blank_lines", "meta_comment", "hedging",
    "redundant_adverbs", "examples_trim", "logical_connector",
    "filler_particles", "punctuation_compress", "punctuation_normalize",
    "condition_clause", "redundant_enum", "semantic_compress",
]

# 类别执行顺序：前 5 位与 v2.5 执行顺序逐字一致，保障零回归（P0-3）。
# duplicate_clauses 紧贴 duplicate_lines（同属去重族）；punctuation_compress 置末。
# 两者均不进 PRESETS → rules=None 路径永不含它们，零回归由结构保证。
CANONICAL_ORDER: list[str] = [
    "empty_items", "duplicate_lines", "duplicate_clauses", "blank_lines",
    "courtesy_boilerplate", "politeness", "first_person", "role_prefix",
    "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
    "logical_connector", "filler_particles", "punctuation_compress",
    "punctuation_normalize", "condition_clause", "redundant_enum",
    "semantic_compress",
]

# 预设 ↔ rules 映射（仅用于 ``rules is None`` 的向后兼容路径）。
# 注意：必须逐字等于 v2.5（不含任何新类别），否则破坏 P0-3 零回归。
# 新类别通过前端默认勾选 + 显式下发 rules 生效，不在此处。
PRESETS: dict[str, list[str]] = {
    "balanced": [
        "politeness", "role_prefix", "empty_items",
        "duplicate_lines", "blank_lines",
    ],
    "aggressive": [
        "politeness", "role_prefix", "empty_items",
        "duplicate_lines", "blank_lines",
    ],
}

# --------------------------------------------------------------------------- #
# 填充词表（按模式分档，逐字沿用 v2.5）
# --------------------------------------------------------------------------- #
# 含「请」的安全词（被误删会破坏语义，如 申请/请求/请教）。先整体保护再还原。
_PROTECT_WORDS = [
    "申请", "请求", "请教", "聘请", "请假", "邀请", "请柬", "请客",
    "请愿", "敬请", "请君", "请战", "请罪", "请安", "请示", "请降",
]

# 中文礼貌/冗余短语（整词移除）
_CN_FILLERS_BALANCED = [
    "请您", "请你", "请务必", "请确保", "请一定要", "请不要", "请尽量",
    "请不要担心", "我希望你", "我希望", "我想让你", "我想请你", "我想要你",
    "我需要你", "你需要", "你应该", "你必须", "你应当", "您应该", "您必须",
    "如果您愿意", "在可能的情况下", "如果有需要", "必要时", "可以的话",
    "在您方便的时候", "如果方便的话", "非常感谢", "十分感谢", "感谢您",
    "感谢你", "谢谢", "麻烦您", "辛苦您", "您好", "你好", "亲",
]
_CN_FILLERS_AGGRESSIVE = [
    "请", "麻烦", "劳烦", "辛苦", "拜托", "尽量", "最好", "一定",
    "务必", "尽可能", "尽可能地", "记得", "注意",
]

# 英文礼貌/冗余短语（大小写不敏感，按词移除）
_EN_FILLERS_BALANCED = [
    "please", "could you", "can you", "would you", "would you please",
    "i want you to", "i need you to", "i would like you to",
    "i'd like you to", "you must", "you should", "you need to",
    "make sure to", "you are required to", "kindly", "thank you",
    "thanks", "hi,", "hello,",
]
_EN_FILLERS_AGGRESSIVE = [
    "you are a", "you are an", "your task is to", "your job is to",
    "your role is to", "you will", "just", "simply", "very", "really",
    "actually", "basically", "in order to", "i am going to",
]

# 冗长角色描述前缀 → 精简前缀（仅行首安全替换）
_ROLE_PREFIXES = [
    ("你是一个专业的", "角色："), ("你是一位专业的", "角色："),
    ("你是一个", "角色："), ("你是一名", "角色："), ("你是一位", "角色："),
    ("我希望你扮演", "角色："), ("请你扮演", "角色："), ("请扮演", "角色："),
    ("you are a", "Role:"), ("you are an", "Role:"),
    ("your task is to act as", "Role:"), ("act as a", "Role:"),
    ("act as an", "Role:"), ("i want you to act as", "Role:"),
]

# 中文角色前缀（供 aggressive 模式行内兜底移除；按长度降序避免短串误匹配长串）
_ROLE_PREFIX_CN = sorted(
    [
        "你是一个专业的", "你是一位专业的", "我希望你扮演",
        "你是一个", "你是一名", "你是一位", "请你扮演", "请扮演",
    ],
    key=len,
    reverse=True,
)

# 空列表项：行首 -, *, •, + 或 数字./) 或 字母./) 之后无实际内容
_EMPTY_BULLET_RE = re.compile(
    r"^\s*([-*•+]\s+|\d+[.)]\s+|[a-z][.)]\s+)\s*$",
    re.IGNORECASE,
)
# 行内代码 / fenced 代码块 / URL 占位（先保护这些片段，避免被误改）
_PROTECT_RE = re.compile(
    r"```[\s\S]*?```"          # fenced code block
    r"|`[^`\n]+`"              # inline code
    r"|https?://[^\s)\]'\"]+"  # url
)
_PROTECT_TOKEN_RE = re.compile(r"\x00P(\d+)\x00")
_KEEP_TOKEN_RE = re.compile(r"\x00K(\d+)\x00")

# --------------------------------------------------------------------------- #
# v2.6 新增规则词典（仅当用户显式勾选时生效；不在 PRESETS 中）
# --------------------------------------------------------------------------- #
# 元评论 / 过渡句：删除后几乎不改变任务语义（仅当用户勾选 meta_comment）。
_META_COMMENT = [
    "需要注意的是", "总的来讲", "总的来说", "简单而言", "简单来说",
    "简而言之", "换句话说", "换言之", "我会帮你", "让我来帮你",
    "让我来", "当然，", "当然。", "当然 ", "此外", "另外",
    "除此之外", "综上所述", "总而言之", "总的来看", "说白了",
    "老实说", "不瞒你说", "顺便说一下", "顺带一提", "话说回来",
    "回到正题", "补充一下", "多说一句", "再补充一点",
]

# evo2-12 召回扩展（仅 explicit/预设路径生效，不影响 rules=None 零回归）：更多元评论/过渡套话
_META_COMMENT += [
    "说真的", "坦白说", "直白地说", "实话实说", "坦白地讲", "简言之", "说实在的",
]

# 弱语气 / 不确定性词（带否定前瞻，避免「不可能→不」「不完全→不」）。
_HEDGING = [
    "可能", "也许", "大概", "或许", "似乎", "恐怕", "某种程度上",
    "一般来说", "不妨", "大致", "约莫", "说不定", "没准",
]

# 冗余副词 / 强调（带否定前瞻，避免误伤「不完全」等）。
_REDUNDANT_ADV = [
    "非常", "十分", "极其", "彻底", "完全", "绝对", "特别",
    "相当", "真的", "实在", "蛮", "超",
]

# evo2-12 召回扩展（仅 explicit/预设路径生效）：更多冗余强调副词（仍带否定前瞻 + 区分性保护）
_REDUNDANT_ADV += [
    "格外", "分外", "尤为", "着实", "甚为", "倍加", "异常",
]

# 示例引导词（examples_trim 触发；英文大小写不敏感）。
_EXAMPLE_LEAD_WORDS = [
    "例如", "例如：", "比如", "比如：", "举个例子", "举个例", "诸如",
    "譬如", "示例如下", "例子如下", "具体如下",
    "e.g.", "for example", "for instance", "such as",
]

# 否定前瞻（多长度固定宽度，覆盖 1~3 字内的否定辖域）：
# 既防「不完全」(紧贴前一字)，也防「不可能完全 / 并没有完全」(隔 1~2 字) 这类结构，
# 避免误删被否定保护的强调 / 弱语气副词（redundant_adverbs / hedging）。
_NEG_CHARS = "不没别未无莫非勿"
_NEG_LOOKBEHIND = "".join(
    f"(?<!{c})(?<!{c}.)(?<!{c}..)" for c in _NEG_CHARS
)


# --------------------------------------------------------------------------- #
# evo2-7 新增规则词典（逻辑连接词 / 句末语气词；仅 explicit 路径 / 显式勾选生效）
# --------------------------------------------------------------------------- #
# 条件/控制流标记：硬排除，永不进入 _LOGICAL_CONNECTORS（避免误删「如果/则/否则」等
# 控制结构）。仅作文档与防护参考，不进任何移除集。
_CONDITIONAL_MARKERS = [
    "如果", "若", "假如", "假使", "一旦", "只要", "只有", "则", "那么",
    "否则", "除非", "不然", "要不然", "假若", "要是", "倘若",
]

# 逻辑/序列/总结/过渡连接词（草案）
_LOGICAL_CONNECTORS_DRAFT = [
    # 因果
    "因此", "所以", "故", "故此", "故而", "因而", "于是", "由此可见", "正因如此", "由此看来",
    # 转折
    "然而", "但是", "不过", "可是", "却", "反倒", "相反", "与之相反", "话虽如此", "尽管如此",
    # 顺承/序列（有序列表行内受保护）
    "首先", "其次", "然后", "接着", "随后", "最后", "最终", "一来", "二来", "再者", "进而", "与此同时",
    # 并列/增补
    "另外", "此外", "还有", "另一方面", "除此之外", "以及", "并且", "同时",
    # 总结
    "总之", "总而言之", "总的来说", "总的来讲", "总的来看", "综上", "综上所述", "一言以蔽之", "概括地说",
    # 解释/强调
    "其实", "事实上", "实际上", "具体来说", "具体而言", "换句话说", "换言之", "也就是说",
    "需要注意的是", "值得一提的是", "值得注意的是", "明确地说", "说白了", "老实说", "不瞒你说",
    # 话题
    "话说回来", "言归正传", "回到正题", "顺便说一下", "顺带一提", "补充一下", "多说一句", "再说一句", "再补充一点",
]

# evo2-12 召回扩展（仅 explicit/预设路径生效）：更多逻辑/总结/过渡连接词（条件标记永不进集）
_LOGICAL_CONNECTORS_DRAFT += [
    "在此基础上", "即便如此", "从而", "由此", "就这点而言", "从这个角度", "顺带说一句",
]
# 去重：排除已属 _META_COMMENT 的词（保持 _META_COMMENT 不变，仅逻辑连接词侧去重，
# 避免「另外/此外/换句话说…」在两者同启时被重复计数）。
_LOGICAL_CONNECTORS = [w for w in _LOGICAL_CONNECTORS_DRAFT if w not in set(_META_COMMENT)]

# 序列连接词（有序列表行内受局部哨兵保护，不删）
_SEQUENCE_CONNECTORS = [
    "首先", "其次", "然后", "接着", "随后", "最后", "最终",
    "一来", "二来", "再者", "进而", "同时", "与此同时",
]

# 句末语气助词（「吗」刻意不纳入移除集，保留疑问句意图）
_FILLER_PARTICLES = list("啊呢吧嘛呀哦啦哈嗯哟嘞咯呗呐嗷诶额呃咪噻捏哇耶喔喏啵")

# politeness 扩展集（仅 explicit=True 叠加；不含裸「请」，单字「请」由下方正则处理）
_CN_FILLERS_EXPANDED = [
    "能否", "可否", "是否可以", "可不可以", "可以吗", "行吗", "好吗", "方便吗",
    "不介意的话", "如果可以的话", "帮我", "替我", "辛苦了", "费心", "劳驾",
    "麻烦您", "拜托你", "求你", "拜托", "劳烦",
]

# 有序列表行识别（用于保护行内序列连接词）
_ORDERED_LIST_LINE_RE = re.compile(
    r"^\s*(?:\d+[.、)）]|\(\d+\)|第[一二三四五六七八九十百零\d]+[、.]|"
    r"[-*•+]\s*第|步骤[一二三四五六七八九十百零\d]+)"
)

# hedging 强化（P1，仅追加多字安全词；刻意排除单字「应」，避免误伤「应用/响应/答应」）
# evo2-11：移除「应该」——指令语境（"你应该返回 JSON"）中是强约束而非弱语气，误删风险高（P0-3 高优先修复）。
_HEDGING += [
    "估计", "想必", "多半", "八成", "兴许", "难免", "基本上", "大体上",
    # evo2-12 召回扩展：更多弱语气/不确定性/泛化表述（仍带否定前瞻，避免误伤「不可能」）
    "未免", "约略", "大抵", "十有八九", "保不齐", "搞不好", "大致上",
]

# evo2-13：hedging「诚实不确定性」前向护栏——认知不确定性类 hedge 后接负面结果词时
# 保留，防「可能不可行」→「不可行」的或然→必然语义翻转。
# 仅用多字词（刻意不含裸「不/没」），且只对「认知不确定性」类 hedge 生效，避免误保
# 表程度/必然的 hedge（难免/基本上/未免…）影响既有召回。
_HEDGING_EPISTEMIC = {
    "可能", "也许", "或许", "大概", "恐怕", "估计", "搞不好", "说不定",
    "保不齐", "八成", "十有八九", "兴许", "多半", "约略", "大抵",
}
# 负面结果词（多字，语义上为「失败/问题/风险」等 undesirable outcome；刻意不含裸「不/没」）：
_HEDGING_NEG_RESULT = [
    "不行", "不对", "不好", "不能", "不会", "不该", "不宜", "不可行", "不可取",
    "不妥", "不成立", "不符合", "不一致", "不通过", "不生效", "不可用", "不支持",
    "不兼容", "不稳定", "不准确", "失败", "出错", "错误", "问题", "风险", "损坏",
    "丢失", "异常", "崩溃", "遗漏", "偏差", "隐患", "缺陷", "漏洞", "瘫痪", "拒绝",
    "超时", "中断", "卡顿", "无效", "副作用", "失误", "延误", "误判", "失真", "冲突",
    "故障", "报错", "不足", "下降", "恶化", "事故", "损失", "危害",
]
# hedge 与负面结果词之间可间隔 1~2 个弱连接小品词（会/要/而/就/则/将/是/得/也/可/能/
# 必/有/出/生/致/引/导/让/使/令/把…）：覆盖「也许会有问题」「搞不好会失败」等。
_HEDGING_NEG_LINK = set("会要而就则将是得也可能必有用出生致引导让使令把将")


def _is_honest_uncertainty(work: str, end: int) -> bool:
    """hedge 后（可间隔 1~2 个弱连接小品词）紧跟负面结果词 → 诚实不确定性，保留 hedge。"""
    rest = work[end:]
    if not rest:
        return False
    for t in _HEDGING_NEG_RESULT:
        if rest.startswith(t):
            return True
    max_k = min(2, len(rest) - 1)
    for k in range(1, max_k + 1):
        if all(c in _HEDGING_NEG_LINK for c in rest[:k]) and \
           any(rest[k:].startswith(t) for t in _HEDGING_NEG_RESULT):
            return True
    return False


# --------------------------------------------------------------------------- #
# evo2-11 新增规则常量（第一人称自指冗余 first_person + 现有规则深化保护集）
# --------------------------------------------------------------------------- #
# 第一人称自指冗余词表（长→短排序；短语级 replace；否定护栏复用 _NEG_LOOKBEHIND）
_FIRST_PERSON = {
    # 受益 / 对象标记（均 2 字，无重叠；「和我/与我」因并列歧义单列，见 comitative）
    "benefit":    ["给我", "为我", "替我", "由我", "同我", "向我", "对我", "帮我"],
    # 并列歧义标记：仅「+动词」才删，避免误删「我和张三/与你与我」等并列构式
    "comitative": ["和我", "与我"],
    # 视角 / 意见标记（长→短）
    "perspective":["以我之见", "我个人觉得", "我个人认为", "在我看来", "依我看", "照我说"],
    # 意愿 / 需求标记（3 字在前，裸「我想」由动词锚定专项处理，不在此表）
    "intent":     ["我想要", "我希望", "我需要", "我打算", "我计划", "我要求",
                   "我期待", "我建议", "我考虑"],
    # 客套求助（长→短）
    "polite_ask": ["请帮我", "麻烦帮我", "劳烦帮我", "求你帮我", "麻烦你帮我"],
}

# evo2-12 召回扩展（仅 explicit 路径生效）：补充第一人称自指标记，提高检测召回
_FIRST_PERSON["benefit"]     += ["代我", "为咱", "替咱"]
_FIRST_PERSON["perspective"] += ["依我之见", "以我看", "拿我来说", "就我而言", "以我看来"]
_FIRST_PERSON["intent"]      += ["我以为", "我寻思", "我琢磨", "我企图", "我奢望"]
# 「和我/与我」后接动词才删（承载请求语义的自指标记），如「和我确认/与我讨论/和对齐」；
# 后接人名/代词（「我和张三」）或普通名词（「和我吃饭」）则保留，避免误删并列/邀约构式。
_FIRST_PERSON_COMITATIVE_VERBS = {
    "确", "对", "查", "核", "检", "讨", "商", "沟", "谈", "聊", "说", "讲", "碰",
    "协", "约", "见", "会", "联", "配", "合", "比", "认", "通", "同", "议", "问",
    "审", "定", "量", "算", "选", "排", "安", "组", "整", "调",
}
_COMITATIVE_VERB_CLASS = "[" + "".join(sorted(_FIRST_PERSON_COMITATIVE_VERBS)) + "]"
# 「我想」动词锚定集：仅当「我想」紧接下列动词之一才删（避免误删「我想你/我想家」）
_FIRST_PERSON_INTENT_VERBS = {
    "做", "要", "让", "看", "知", "去", "写", "创", "生", "实", "了", "学", "找",
    "问", "改", "加", "用", "试", "听", "说", "想", "帮", "得", "会", "能", "懂",
    "搞", "弄",
}
# 去重排序为字符类（确定性，避免 hash 顺序依赖）
_FIRST_PERSON_INTENT_VERB_CLASS = "[" + "".join(sorted(_FIRST_PERSON_INTENT_VERBS)) + "]"

# 冗余副词区分性保护：后接对比词（不同/相反/独立/新的/差异/区别/区分等）时不删，
# 保留「完全不同于…」「绝对独立的…」等承载区分语义的用法（redundant_adverbs 深化，P0-3）。
_REDUNDANT_ADV_DISCRIMINATIVE = [
    "不同", "相反", "独立", "新的", "差异", "区别", "区分",
]

# 元评论纯过渡保护：仅句首且后接 逗号/句号 才删（深化 P0-3）；其余仍短语级删除。
_META_COMMENT_STRICT = [
    "需要注意的是", "值得注意的是", "明确地说", "具体来说", "具体而言",
]

# 无序列表行识别（用于保护行内序列连接词，避免误删步骤提示「首先/然后/最后」，P1-2）
_UNORDERED_LIST_LINE_RE = re.compile(r"^\s*[-*•+]\s")

# --------------------------------------------------------------------------- #
# evo2-12 新增规则常量（客套/寒暄冗余 courtesy_boilerplate，explicit-only）
# --------------------------------------------------------------------------- #
# 客套/寒暄/礼貌冗余词表（长→短排序；短语级 replace；纯 boilerplate，无需否定护栏）。
# 分五组：①招呼 ②道歉 ③感谢 ④客套求助（条件式） ⑤结尾套话。
# 设计取舍：仅删「纯礼貌噪声」，不删承载指令语义的词（如「请/麻烦」由 politeness 处理，
# 此处只收「你好/谢谢/抱歉/辛苦了/仅供参考」等无信息量套话）；「谢谢你/感谢你」整体删
# （长词优先于「谢谢」），避免残留孤立「你」。
_COURTESY_BOILERPLATE = {
    "greeting":  ["大家好", "你们好", "你好啊", "您好", "你好", "在吗", "在不在", "嗨", "哈喽", "哈啰"],
    "apology":   ["对不起", "抱歉", "不好意思", "劳驾", "打扰了", "打扰一下", "见谅"],
    "thanks":    ["十分感谢", "不胜感激", "多谢", "感谢您", "谢谢你", "感谢你", "谢谢", "感谢", "辛苦了", "麻烦了"],
    "hedged_ask":["如果可以的话", "如果方便的话", "若可以的话", "若方便的话", "可以的话", "方便的话"],
    "closer":    ["仅供参考", "不吝赐教", "敬请谅解", "如有问题", "如有疑问", "请知悉", "望知悉", "顺祝", "祝好"],
}
# 展平为去重、长→短排序的短语列表（供单条正则 `最长优先` 匹配，避免「谢谢你」被「谢谢」截短）
_COURTESY_PHRASES = sorted(
    (p for grp in _COURTESY_BOILERPLATE.values() for p in grp),
    key=lambda s: (-len(s), s),
)
_COURTESY_RE = re.compile("|".join(re.escape(p) for p in _COURTESY_PHRASES))

# --------------------------------------------------------------------------- #
# evo2-8 新增规则常量（跨句完全重复子句去重 / 连续重复标点折叠；均 explicit-only）
# --------------------------------------------------------------------------- #
# 跨句/跨句完全重复子句去重（方案 B：独立 explicit-only id，不进 PRESETS）。
_DUP_CLAUSE_MIN_LEN = 4          # 非句末子句重复的最小 CJK 字符数（阈值护栏）
# 句末标点（用于切分句子 / 判定"整句重复"与"句末冗余尾词"）
_SENT_END_RE = re.compile(r"[。！？]")

# 连续重复标点折叠（explicit-only；不进 PRESETS）。
# 折叠集 = CJK 。！？ + ASCII ! ?；刻意排除 ASCII `.`，以保护语义省略号 `...`
# （`……` U+2026 / `——` U+2014 本就不在集内，天然排除）。
_PUNCT_FOLD_RE = re.compile(r"([。！？!?])\1{2,}")   # 3+ 同字符 → 单字符

# --------------------------------------------------------------------------- #
# evo2-9 新增规则常量（本地语义压缩 semantic_compress；explicit-only，不进 PRESETS）
# --------------------------------------------------------------------------- #
# 近义/重复句判定阈值（余弦相似度）：≥ threshold 判为语义重复，保留首次、折叠后续。
_SEMANTIC_THRESHOLD_DEFAULT = 0.90   # 默认偏保守（仅高度相似才折叠，防误删）
_SEMANTIC_THRESHOLD_MIN = 0.80      # 滑块/API 下限（更激进去重）
_SEMANTIC_THRESHOLD_MAX = 0.98      # 滑块/API 上限（接近字面相同才删）
# 重要性剪枝（二级能力，默认关）的"低信息"地板：与主题质心相似度低于此值且非指令句 → 折叠。
_SEMANTIC_PRUNE_FLOOR = 0.60
# 抽取式语义压缩保护：含这些标记的句视为"含指令/条件/代码/否定"，剪枝时永不动。
_SEMANTIC_PROTECT_HINTS = (
    "请", "必须", "应该", "需要", "务必", "执行", "调用", "运行", "输出", "返回",
    "使用", "定义", "创建", "删除", "修改", "检查", "验证", "确保", "禁止", "不要",
    "不", "没", "无", "勿", "别", "若", "如果", "除非", "否则", "`", "http", "www.",
)

# evo2-13：语义剪枝「重要性」门控——受 AGENTS.MD「保留 useful substance」启发。
# 仅当句「离题 且 低信息」时才剪；离题但含实质（含指令/数字/专名）的句保留，
# 防误删有价值的背景信息。评分落在 [0,1]，低于地板才允许剪。
_SEMANTIC_IMPORTANCE_HINTS = (
    "请", "必须", "需要", "应该", "务必", "执行", "调用", "运行", "输出", "返回",
    "使用", "定义", "创建", "删除", "修改", "检查", "验证", "确保", "禁止", "不要",
    "若", "如果", "除非", "否则", "步骤", "注意", "重要", "关键", "目标", "要求",
    "配置", "参数", "函数", "接口", "数据", "模型", "示例", "格式", "输入", "地址",
    "原因", "结果", "结论", "方案", "指标", "依赖", "依赖项", "路径", "类型", "字段",
)
_SEMANTIC_IMPORTANCE_FLOOR = 0.35


def _score_sentence_importance(sentence: str) -> float:
    """句级词法重要性评分 [0,1]：含指令/专名、含数字、长度越长 → 越高（越应保留）。"""
    s = sentence.strip()
    if not s:
        return 0.0
    score = 0.0
    # 1) 指令 / 专名提示词命中（最高权重）
    hits = sum(1 for h in _SEMANTIC_IMPORTANCE_HINTS if h in s)
    score += min(hits * 0.20, 0.60)
    # 2) 数字（含小数 / 百分号 / 序号）→ 实质信息
    digits = re.findall(r"\d+", s)
    if digits:
        score += min(0.20 + (len(digits) - 1) * 0.05, 0.35)
    # 3) 有效字符长度（越长越可能含信息）
    eff_len = len(re.sub(r"\s+", "", s))
    if eff_len >= 24:
        score += 0.20
    elif eff_len >= 12:
        score += 0.10
    return min(score, 1.0)


def _semantic_threshold_clamp(v) -> float:
    """语义阈值越界静默回落默认（非法/越界/非数 → 默认 0.90），绝不 500。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _SEMANTIC_THRESHOLD_DEFAULT
    if f != f or f < _SEMANTIC_THRESHOLD_MIN or f > _SEMANTIC_THRESHOLD_MAX:
        return _SEMANTIC_THRESHOLD_DEFAULT
    return f


def _get_semantic_backend():
    """取得可用的稠密语义后端；不可用（无本地 embedding / 非稠密 / 异常）返回 None。

    - 复用 scorer.get_vectorizer() 的 local-st EmbeddingBackend（零新增依赖）；
    - 仅当其为稠密后端（is_dense_backend）才返回，否则视为"embedding 不可用"→ 跳过；
    - 任何异常（端点不可达/配置损坏）一律返回 None，由调用方静默跳过语义压缩。
    """
    from . import scorer
    try:
        vec = scorer.get_vectorizer()
    except Exception:
        return None
    if not scorer.is_dense_backend(vec):
        return None
    return vec


def _strip_protect_tokens(text: str) -> str:
    """去掉冻结占位符 \\x00...\\x00，避免控制字符污染句向量（占位符本身语义无意义）。"""
    return re.sub(r"\x00[^\x00]*\x00", " ", text)


def _cosine_dense(a: list, b: list) -> float:
    """两个稠密向量余弦相似度，落在 [0,1]。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _rule_semantic_compress(work, aggressive_like, explicit,
                            threshold=_SEMANTIC_THRESHOLD_DEFAULT,
                            prune=False, backend=None):
    """本地语义压缩（抽取式近义/重复句折叠；explicit-only，不进 PRESETS）。

    - 仅 explicit=True（用户显式勾选 semantic_compress）时生效；rules=None 永不触发。
    - 仅当稠密 embedding 后端可用时真正折叠；否则（local-tfidf / 端点不可达 / 异常）
      静默跳过，返回 (work, 0)，绝不 500 / 不抛未捕获异常。
    - 能力1（默认）：按句切分 → 逐句向量 → 两两余弦 ≥ threshold 判语义重复，保留首次、折叠后续。
    - 能力2（semantic_prune=True 时）：以保留句向量质心为「主题向量」，与质心相似度低于
      _SEMANTIC_PRUNE_FLOOR 且无指令/条件/代码/否定的低信息句折叠（不删含指令内容句）。
    - 受保护片段（代码块/URL/行内代码）已在 work 中以占位符原子化，本规则不对其内部断句。
    """
    if not explicit:
        return work, 0
    if backend is None:
        backend = _get_semantic_backend()
    if backend is None:
        return work, 0  # 语义压缩跳过（embedding 不可用）

    # 切句（保留分隔标点；空段丢弃）。占位符在句内保持原子，不额外断句。
    sentences = [s for s in re.split(r"(?<=[。！？])", work) if s]
    if len(sentences) < 2:
        return work, 0

    # 先向量化全部句子（任意单句失败 → 整规则跳过，绝不部分应用）
    stripped = [_strip_protect_tokens(s) for s in sentences]
    try:
        vecs = [backend.vectorize(t) for t in stripped]
    except Exception:
        return work, 0

    kept = []           # 保留句的下标
    folded = 0
    result = list(sentences)
    # 能力1：近义/重复句折叠（保留首次，后续与任一保留句 ≥ threshold 则折叠）
    for i in range(len(sentences)):
        is_dup = False
        for k in kept:
            if _cosine_dense(vecs[i], vecs[k]) >= threshold:
                is_dup = True
                break
        if is_dup:
            result[i] = ""
            folded += 1
        else:
            kept.append(i)

    # 能力2：重要性剪枝（仅 prune=True）。与任一句的最高相似度低于地板 → 离题句；
    # 再经「重要性」门控：仅当离题 且 低信息（无指令/专名/数字）时才折叠，
    # 保留离题但含实质（useful substance）的句，防误删有价值的背景信息。
    if prune and kept:
        for i in list(kept):
            if result[i] == "":
                continue
            if any(h in sentences[i] for h in _SEMANTIC_PROTECT_HINTS):
                continue
            max_sim = max(
                (_cosine_dense(vecs[i], vecs[k]) for k in kept if k != i),
                default=0.0,
            )
            if max_sim < _SEMANTIC_PRUNE_FLOOR:
                # 离题但含实质（高重要性）→ 保留，防误删 useful substance
                if _score_sentence_importance(sentences[i]) >= _SEMANTIC_IMPORTANCE_FLOOR:
                    continue
                result[i] = ""
                folded += 1

    if folded == 0:
        return work, 0
    return "".join(result), folded


# --------------------------------------------------------------------------- #
# 内部工具（逐字沿用 v2.5）
# --------------------------------------------------------------------------- #
def _protect(text: str, store: list[str]) -> str:
    """把需保护的片段（代码块/URL/行内代码）替换为占位符。"""
    def _stash(match: "re.Match[str]") -> str:
        store.append(match.group(0))
        return f"\x00P{len(store) - 1}\x00"

    return _PROTECT_RE.sub(_stash, text)


def _protect_words(text: str, store: list[str], words: list[str]) -> str:
    """保护含填充字的合法词，避免被裸字移除误伤。"""
    for word in words:
        if word in text:
            idx = len(store)
            store.append(word)
            text = text.replace(word, f"\x00K{idx}\x00")
    return text


def _restore(text: str, store: list[str]) -> str:
    """按占位符顺序还原保护片段。"""
    def _rep(match: "re.Match[str]") -> str:
        i = int(match.group(1))
        return store[i] if 0 <= i < len(store) else match.group(0)

    text = _PROTECT_TOKEN_RE.sub(_rep, text)
    text = _KEEP_TOKEN_RE.sub(_rep, text)
    return text


def _norm_line(line: str) -> str:
    """归一化一行用于去重比较：去空白、去标点、小写。"""
    s = line.strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\u3000-\u303f\uff00-\uffef\W_]", "", s)
    return s


def _collapse_blank_lines(text: str) -> str:
    """折叠连续空行（含纯空白行）为至多一个空行，并清理每行首尾空白。"""
    out: list[str] = []
    prev_blank = False
    for line in text.split("\n"):
        if line.strip() == "":
            if prev_blank:
                continue
            out.append("")
            prev_blank = True
        else:
            out.append(line.strip())
            prev_blank = False
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _simplify_role(line: str, aggressive: bool) -> tuple[str, bool]:
    """行首冗长角色描述前缀精简（v2.5 原逻辑，逐字保留）。"""
    stripped = line.lstrip()
    for prefix, repl in _ROLE_PREFIXES:
        if stripped.startswith(prefix):
            return repl + stripped[len(prefix):], True
    return line, False


def _is_protect_token(line: str) -> bool:
    """该整行是否就是某个保护占位符（代码块/URL/行内代码被冻结为单 token）。"""
    s = line.strip()
    return bool(re.fullmatch(r"\x00[PK]\d+\x00", s))


def _is_lead_line(line: str) -> bool:
    """判断该行是否为示例引导行（含任意引导词）。"""
    low = line.lower()
    for w in _EXAMPLE_LEAD_WORDS:
        if w.lower() in low:
            return True
    return False


# --------------------------------------------------------------------------- #
# 规则函数（统一签名 fn(work, aggressive_like) -> (work, count)）
# 除 politeness / role_prefix 外，其余忽略 aggressive_like。
# --------------------------------------------------------------------------- #
def _rule_politeness(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """礼貌/冗余填充词移除（v2.5 原逻辑；aggressive_like 控制单字「请」）。

    ``explicit=True`` 时叠加 ``_CN_FILLERS_EXPANDED`` 扩展集，且单字「请」也移除
    （实现"默认更强"）；``explicit=False``（rules=None 路径）仅用 v2.5 原表，逐字不动。
    """
    cn_fillers = list(_CN_FILLERS_BALANCED)
    en_fillers = list(_EN_FILLERS_BALANCED)
    if aggressive_like:
        cn_fillers += _CN_FILLERS_AGGRESSIVE
        en_fillers += _EN_FILLERS_AGGRESSIVE
    if explicit:                      # 仅显式路径叠加扩展集
        cn_fillers += _CN_FILLERS_EXPANDED

    filler_removed = 0
    for phrase in en_fillers:
        cnt = work.lower().count(phrase)
        if cnt:
            work = re.sub(r"(?i)" + re.escape(phrase), "", work)
            filler_removed += cnt
    for phrase in cn_fillers:
        cnt = work.count(phrase)
        if cnt:
            work = work.replace(phrase, "")
            filler_removed += cnt
    if aggressive_like or explicit:   # 单字「请」在显式路径也移除
        cnt = len(re.findall(r"请(?=[一-鿿])", work))
        if cnt:
            work = re.sub(r"请(?=[一-鿿])", "", work)
            filler_removed += cnt
    return work, filler_removed


def _rule_role_prefix(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """冗长角色前缀精简（v2.5 原逻辑；aggressive_like 控制 5.b 行内兜底）。"""
    role_hits = 0
    out_lines = []
    for line in work.split("\n"):
        new_line, hit = _simplify_role(line, aggressive_like)
        if hit:
            role_hits += 1
        out_lines.append(new_line)
    work = "\n".join(out_lines)

    if aggressive_like:
        new_out: list[str] = []
        for line in out_lines:
            for prefix in _ROLE_PREFIX_CN:
                if prefix in line:
                    line = line.replace(prefix, "")
                    role_hits += 1
            new_out.append(line)
        out_lines = new_out
        work = "\n".join(out_lines)
    return work, role_hits


def _rule_empty_items(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """空列表项 / 空编号移除。"""
    lines = work.split("\n")
    kept: list[str] = []
    removed = 0
    for line in lines:
        if _EMPTY_BULLET_RE.match(line):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed


def _rule_duplicate_lines(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """重复 / 近 identical 指令合并（归一化后去重）。"""
    lines = work.split("\n")
    kept: list[str] = []
    seen_norm: dict[str, int] = {}
    removed = 0
    for line in lines:
        norm = _norm_line(line)
        if norm:
            if norm in seen_norm:
                removed += 1
                continue
            seen_norm[norm] = 1
        kept.append(line)
    return "\n".join(kept), removed


def _rule_blank_lines(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """折叠连续空行为至多 1 个。"""
    new = _collapse_blank_lines(work)
    return new, 0


def _rule_meta_comment(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """元评论 / 过渡句短语级移除（不破坏主干）。

    evo2-11 深化（P0-3）：_META_COMMENT_STRICT 中的纯过渡词（需要注意的是/值得注意的是/
    明确地说/具体来说/具体而言）仅在句首（文本起始或前接 。！？\\n）且后接 ，/。 时才删，
    否则保留——避免误删引出关键约束的过渡。
    """
    cnt = 0
    # 普通元评论：短语级移除
    for phrase in _META_COMMENT:
        if phrase in _META_COMMENT_STRICT:
            continue
        c = work.count(phrase)
        if c:
            work = work.replace(phrase, "")
            cnt += c
    # 严格过渡词：仅句首（^ 或 前接 。！？\\n）且后接 ，/。 才删
    # 严格过渡词：仅句首（^ 或 前接 。！？\n）且后接 ，/。 才删；同时吃掉紧随的标点，
    # 避免残留孤立逗号（「需要注意的是，任务很简单。」→「任务很简单。」）
    strict_re = (
        r"(?:(?<=^)|(?<=[。！？\n]))"
        + "(?:" + "|".join(re.escape(w) for w in _META_COMMENT_STRICT) + ")"
        + r"[，。]"
    )
    matches = re.findall(strict_re, work)
    if matches:
        work = re.sub(strict_re, "", work)
        cnt += len(matches)
    return work, cnt


def _rule_hedging(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """弱语气 / 不确定性词移除（带否定前瞻 + 诚实不确定性前向护栏）。

    evo2-13：当 hedge 属于「认知不确定性」类（可能/也许/搞不好…）且其**后**（可间隔
    1 个连接小品词）紧跟负面结果词（不可行/失败/问题…多字词）时，**保留**该 hedge，
    防止「可能不可行」→「不可行」的或然→必然语义翻转。其余 hedge 照常移除。
    """
    cnt = 0
    for phrase in _HEDGING:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase)
        matches = [
            (m.start(), m.end()) for m in re.finditer(pattern, work)
            if not (phrase in _HEDGING_EPISTEMIC and _is_honest_uncertainty(work, m.end()))
        ]
        if matches:
            for s, e in sorted(matches, reverse=True):
                work = work[:s] + work[e:]
            cnt += len(matches)
    return work, cnt


def _rule_redundant_adverbs(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """冗余副词 / 强调移除（带否定前瞻，避免误伤「不完全/并没有完全」等）。

    evo2-11 深化（P0-3）：区分性保护——副词后接对比词（不同/相反/独立/新的/差异/
    区别/区分）时不删，保留「完全不同于…」「绝对独立的…」等承载区分语义的用法。
    """
    cnt = 0
    protect_lookahead = "(?!" + "|".join(re.escape(w) for w in _REDUNDANT_ADV_DISCRIMINATIVE) + ")"
    for phrase in _REDUNDANT_ADV:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase) + protect_lookahead
        matches = re.findall(pattern, work)
        if matches:
            work = re.sub(pattern, "", work)
            cnt += len(matches)
    return work, cnt


def _rule_examples_trim(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """过长示例压缩（默认关闭，仅显式勾选时生效）。

    识别「示例引导词」之后的连续非空行块；超阈值（≥4 行 或 ≥200 字符）折叠为
    「前 3 条真实示例行」+ 追加标注「（示例已压缩，共 X 行）」。

    无损保证：受保护 token 行（代码块 / URL / 行内代码）永远原样保留；若块内含受
    保护内容，则全部真实示例行也一并保留（绝不因代码块占用「前 3 行」名额而把
    用户真实内容挤出丢弃）。
    """
    lines = work.split("\n")
    out: list[str] = []
    i = 0
    blocks = 0
    while i < len(lines):
        line = lines[i]
        if _is_lead_line(line):
            block: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != "":
                block.append(lines[j])
                j += 1
            total = len(block)
            chars = sum(len(x) for x in block)
            if total >= 4 or chars >= 200:
                has_protect = any(_is_protect_token(bl) for bl in block)
                out.append(line)
                if has_protect:
                    # 含受保护内容（代码块 / URL / 行内代码）→ 无损保留全部行
                    out += block
                else:
                    # 纯文本示例：仅保留前 3 条真实行，其余压缩
                    out += block[:3]
                out.append(f"（示例已压缩，共 {total} 行）")
                blocks += 1
                i = j
            else:
                out.append(line)
                out += block
                i = j
        else:
            out.append(line)
            i += 1
    return "\n".join(out), blocks


def _rule_logical_connector(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """逻辑/序列/总结/过渡连接词移除（带否定前瞻，避免「不因此→不」）。

    仅删不携带"要模型做什么"语义的连接词；条件/控制流标记（_CONDITIONAL_MARKERS）
    永不进入 _LOGICAL_CONNECTORS，故不会被误删。

    编号/有序列表语境保护：行首命中 _ORDERED_LIST_LINE_RE 的行，其行内序列连接词
    （_SEQUENCE_CONNECTORS）先以规则内局部哨兵 \\x01K<n>\\x01 暂存（与外层 _protect/
    _restore 的 \\x00 命名空间隔离），移除游离连接词后再还原——既不污染外层 _restore、
    也不会被重复计数。非列表语境中的序列词仍正常移除。
    """
    # 1) 有序/无序列表行：用局部哨兵保护行内序列词（P1-2：无序列表行也纳入保护）
    local_store: list[str] = []
    lines = work.split("\n")
    for i, line in enumerate(lines):
        if _ORDERED_LIST_LINE_RE.match(line) or _UNORDERED_LIST_LINE_RE.match(line):
            for w in _SEQUENCE_CONNECTORS:
                if w in line:
                    idx = len(local_store)
                    local_store.append(w)
                    line = line.replace(w, f"\x01K{idx}\x01")
            lines[i] = line
    work = "\n".join(lines)

    # 2) 移除游离连接词（受否定前瞻保护，条件标记本就不在 _LOGICAL_CONNECTORS）
    removed = 0
    for phrase in _LOGICAL_CONNECTORS:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase)
        matches = re.findall(pattern, work)
        if matches:
            work = re.sub(pattern, "", work)
            removed += len(matches)

    # 3) 还原局部哨兵（序列词），不污染外层 _restore 的 \\x00 命名空间
    def _rep(match: "re.Match[str]") -> str:
        j = int(match.group(1))
        return local_store[j] if 0 <= j < len(local_store) else match.group(0)

    work = re.sub(r"\x01K(\d+)\x01", _rep, work)
    return work, removed


def _rule_filler_particles(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """句末语气助词移除（啊/呢/吧/嘛/呀/哦/啦/哈/嗯/哟/嘞…）。

    - 仅句末（后接 。！？.!?… 或文末）移除，句中谨慎不删，避免误伤必要衔接。
    - 「吗」刻意不纳入移除集，保留疑问句意图（PRD Q4）。
    - 叠加否定前瞻，避免「不啊→不」误删（硬约束）。
    """
    removed = 0
    tail = r"(?=[。！？\.!?\…]|\Z)"
    for w in _FILLER_PARTICLES:
        pattern = _NEG_LOOKBEHIND + re.escape(w) + tail
        matches = re.findall(pattern, work)
        if matches:
            work = re.sub(pattern, "", work)
            removed += len(matches)
    return work, removed


def _cjk_len(text: str) -> int:
    """返回文本中 CJK 字符个数（用于重复去重的阈值护栏）。"""
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _rule_duplicate_clauses(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """跨句/跨句完全重复子句去重（方案 B：独立 explicit-only id，不进 PRESETS）。

    - 仅当用户显式勾选（explicit=True）时生效；rules=None 路径永不触发，保障零回归。
    - 两分支阈值（删冗余副本，保留一个完整副本；绝不残留游离标点，绝不删关键名词）：
      (a) 整句精确重复：以 。！？ 收尾的整句（去尾标点后 ≥2 个 CJK 字）在前文逐字出现
          → 整句丢弃（含其尾标点），不产生 。。 之类游离标点。
      (b) 长重复前缀：前文某整句（去尾标点，≥ _DUP_CLAUSE_MIN_LEN 个 CJK 字）是本句前缀
          → 仅保留新增后缀；若后缀为空或仅剩标点（即本句恰为前文句的精确重复 + 标点）
          → 整句丢弃，同样不产生游离标点。
    - 受保护片段（代码块/URL/行内代码）已被冻结为占位符，不同占位符天然不互匹，不会跨代码块误并。
    - 否定/条件不丢：删的是冗余副本，保留副本自带其语义。
    - 设计取舍：刻意不做「句末尾词」去重——该操作无法区分冗余收尾词（总结/如下）与关键名词
      （报告/字段），易误删宾语，违反 PRD §6「不丢关键信息」硬约束，故移除。
    """
    if not explicit:
        return work, 0
    sentences = re.split(r"(?<=[。！？])", work)
    seen: list[str] = []
    out: list[str] = []
    removed = 0
    for s in sentences:
        if not s:
            continue
        core = re.sub(r"[。！？]+$", "", s)
        # (a) 整句精确重复（任意长度 ≥2 CJK）→ 整句丢弃，绝不残留游离标点
        if _cjk_len(core) >= 2 and core in seen:
            removed += 1
            continue
        # (b) 长重复前缀 → 仅保留新增后缀；后缀为空/仅标点则整句丢弃
        new_s = s
        for prev_core in seen:
            if _cjk_len(prev_core) >= _DUP_CLAUSE_MIN_LEN and s.startswith(prev_core):
                suffix = s[len(prev_core):]
                if suffix.startswith(" "):
                    suffix = suffix[1:]
                suffix_core = re.sub(r"[。！？]+$", "", suffix)
                if _cjk_len(suffix_core) >= 1:
                    new_s = suffix
                    removed += 1
                else:
                    new_s = ""
                    removed += 1
                break
        if new_s == "":
            continue  # 整句丢弃：避免产生 「。。」之类游离标点
        seen.append(core)
        out.append(new_s)
    return "".join(out), removed


def _rule_punctuation_compress(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """折叠 3+ 连续 。！？.!? → 单字符（explicit-only，不进 PRESETS）。

    - 折叠集刻意排除 ASCII `.`，以保护语义省略号 `...`；`……`/`——` 本就不在集内天然排除。
    - 代码/行内代码/URL 内标点受 `_protect` 冻结为占位符，不会被触碰。
    """
    if not explicit:
        return work, 0
    new, n = _PUNCT_FOLD_RE.subn(r"\1", work)
    return new, n


def _rule_punctuation_normalize(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """标点归一化（explicit-only，不进 PRESETS）：折叠 2+ 连续相同标点 + 规整标点周围空格。

    - 与 ``punctuation_compress``（仅 3+ 连续）互补：本规则把 2+ 连续相同的常用
      CJK 标点（，。！？；：、）折叠为单个，并删除这些标点紧邻的半角/全角空格
      （如「你好 ， 世界」→「你好，世界」；「你好　，　世界」→「你好，世界」）。
    - 仅归一化**冗余**，绝不删除有语义的标点（单标点、引号、括号等原样保留）。
    - 代码/行内代码/URL 内标点受 ``_protect`` 冻结为占位符，不会被触碰。
    """
    if not explicit:
        return work, 0
    # 统计「处」：2+ 连续相同标点组数 + 标点周围多余空格（半角 \t 与全角 　 均计）对数
    # 显式用 [ \t\u3000] 而非 \s，避免跨 Python 版本对全角空格（U+3000）匹配的歧义。
    _WS = r"[ \t\u3000]"
    n_fold = len(re.findall(r"([，。！？；：、])\1+", work))
    n_space = len(re.findall(_WS + r"+[，。！？；：、]", work)) + len(re.findall(r"[，。！？；：、]" + _WS + r"+", work))
    count = n_fold + n_space
    if count == 0:
        return work, 0
    # 用 \1*（而非 \1+）匹配整段连续相同标点，一次性折叠为单个，
    # 避免奇数长度（如 ，，，）→ 残留 ，， 的缺陷。
    folded = re.sub(r"([，。！？；：、])\1*", r"\1", work)
    folded = re.sub(_WS + r"+([，。！？；：、])", r"\1", folded)   # 标点前空格（半/全角）
    folded = re.sub(r"([，。！？；：、])" + _WS + r"+", r"\1", folded)   # 标点后空格（半/全角）
    return folded, count


# --------------------------------------------------------------------------- #
# evo2-15 长文本增强（离线、显式-only、不进 PRESETS，零回归由结构保证）
# --------------------------------------------------------------------------- #
# 条件/保留语境 hedge 短语：删除后主干断言语义不变，纯前提/保留语噪声。
# 这些短语与 courtesy_boilerplate 的「如果方便的话/如果可以的话」有字面重叠，
# 但本表是独立、更全的 caveat 集合；运行顺序上 courtesy 先走（step 4.0），
# 本规则随后对残留 caveat 补刀，互不重复计数（已删的这里 count=0）。
_CAVEAT_HEDGES: list[str] = [
    "如果方便的话", "如果可以的话", "可以的话", "如果有需要的话", "如果有需要",
    "在可能的情况下", "在您方便的时候", "必要时", "如果有余力", "实在不行的话",
    "条件允许的话", "有充足真实依据的话", "有真实依据的话", "真的可以实现的话",
    "可以实现的话", "如果真的可以", "说实话", "说真的", "不夸张地说",
    "客观地说", "平心而论",
]

# 冗余枚举：长文本里「清洗/还原/再清洗/…操作」这类斜杠枚举，含前缀冗余项与末尾 boilerplate 名词。
_REDUNDANT_ENUM_PREFIXES = ("再", "重新", "再次", "重", "复", "再度", "又")
_REDUNDANT_ENUM_TAILS = ("操作", "处理", "工作", "动作", "流程", "行为")
# 比较核前缀：枚举首项（乃至各项）常带前置情态/及物链（可以/会/要/然后/进行/做/执行…），
# 「然后可以进行清洗」的真实核是「清洗」。去重比较前递归剥除这些前缀得到核（输出仍保留原词）。
_ENUM_CORE_PREFIXES = (
    "可以", "会", "要", "想", "应该", "能", "能够", "去", "来", "就", "先", "然后",
    "进行", "做", "执行", "支持", "允许", "用于",
)
# 仅匹配 / 分隔的短项枚举：首项必须是 ≤6 字且以 CJK 开头（避免把「skill 然后可以进行清洗」
# 整段吞进首项、或跨 ASCII 词拆分）；后续项 ≤14 字；遇 CJK 标点/换行即止。
# 受保护片段（代码/URL）此前已占位，不会进入；MCP/skill 等 ASCII 起手枚举因 CJK 起手约束不误触。
_ENUM_GROUP_RE = re.compile(
    r"(?=[一-鿿])([^/，。！？\n]{1,6}/)(?:[^/，。！？\n]{1,14}/)*[^/，。！？\n]{1,14}"
)


def _enum_core(it: str) -> str:
    """递归剥除前置情态/及物前缀，得到枚举项的语义核（如「然后可以进行清洗」→「清洗」）。"""
    s = it
    while True:
        stripped = False
        for p in _ENUM_CORE_PREFIXES:
            if s.startswith(p) and len(s) > len(p):
                s = s[len(p):]
                stripped = True
                break
        if not stripped:
            break
    return s


def _rule_condition_clause(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """条件 / 保留语境 hedge 剪枝（explicit-only）。

    删除无信息量的前提/保留语短语（…的话 / 有充足真实依据的话 / 说实话 / …），
    保留主干断言（「冲突检测真的可以实现的话可以保留」→「冲突检测可以保留」）。
    删除后对残留的孤立/连续逗号做最小规整。
    """
    if not explicit:
        return work, 0
    cnt = 0
    for ph in _CAVEAT_HEDGES:
        c = work.count(ph)
        if c:
            work = work.replace(ph, "")
            cnt += c
    if cnt:
        # 最小规整：句首/句末孤立逗号、连续逗号（不触碰有语义标点）
        work = re.sub(r"(?<=[。！？\n])[，,]+", "", work)
        work = re.sub(r"[，,]+$", "", work)
        work = re.sub(r"[，,]{2,}", "，", work)
    return work, cnt


def _rule_redundant_enum(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """冗余枚举折叠（explicit-only）。

    针对斜杠分隔枚举：① 末项冗余名词尾（操作/处理/工作…）剥除；
    ② 若某项 = 前缀(再/重新/再次…) + 同组另一项 → 删较长冗余项。
    仅作用于 / 分隔的短项枚举，绝不触碰受保护片段（代码/URL 已占位）。
    """
    if not explicit:
        return work, 0
    cnt = 0

    def _clean_group(g: str) -> str:
        nonlocal cnt
        items = g.split("/")
        # ① 剥除末项冗余尾名词（仅当项 > 尾且去除后非空）
        cleaned: list[str] = []
        for it in items:
            for tail in _REDUNDANT_ENUM_TAILS:
                if it.endswith(tail) and len(it) > len(tail):
                    it2 = it[: -len(tail)]
                    if it2:
                        it = it2
                        cnt += 1
                        break
            cleaned.append(it)
        # ② 前缀冗余去重：比较核递归剥除前置情态/及物链（然后进行清洗→清洗），
        #    若 cores[b] == prefix + cores[a] → 删 b（较长冗余）；输出用原词，保留「进行」等动词。
        cores = [_enum_core(it) for it in cleaned]
        keep: list[str] = []
        for i, b in enumerate(cleaned):
            redundant = False
            for j, a in enumerate(cleaned):
                if i == j:
                    continue
                for p in _REDUNDANT_ENUM_PREFIXES:
                    if cores[i] == p + cores[j] and len(cores[i]) > len(cores[j]):
                        redundant = True
                        cnt += 1
                        break
            if not redundant:
                keep.append(b)
        return "/".join(keep)

    return _ENUM_GROUP_RE.sub(lambda m: _clean_group(m.group(0)), work), cnt


def _rule_first_person(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """第一人称自指冗余移除（explicit-only 由调用方控制；不进 PRESETS）。

    - 仅当用户显式勾选（explicit=True）时生效；rules=None 路径永不触发，保障零回归。
    - 删除「给我/为我/替我/由我/同我/向我/对我/帮我」「依我看/在我看来…」
      「我想要/我希望/我需要…」「请帮我/麻烦帮我…」等说话人自己的冗余自指标记；
      「和我/与我」仅当后接动词（如「和我确认/与我讨论」）才删，避免误删「我和张三」并列构式；
      不删裸字「我」（仅在明确受益/意愿构式中才删），降低误删。
    - 「我想」须锚定后接动词（_FIRST_PERSON_INTENT_VERBS）才删，避免误删「我想你/我想家」。
    - 全程在 _NEG_LOOKBEHIND 否定护栏下（别/不/没… 辖域内的自指标记保留，复用现状）。
    - 受保护片段（代码块/URL/行内代码）已由外层 _protect 冻结为占位符，本函数不触碰。
    """
    cnt = 0
    # benefit / perspective / intent / polite_ask：短语级 replace（词表内已长→短排序）
    for group in ("benefit", "perspective", "intent", "polite_ask"):
        for phrase in _FIRST_PERSON[group]:
            pattern = _NEG_LOOKBEHIND + re.escape(phrase)
            matches = re.findall(pattern, work)
            if matches:
                work = re.sub(pattern, "", work)
                cnt += len(matches)
    # comitative（和我/与我）：仅「+动词」才删（动词锚定），避免误删「我和张三」并列构式
    for phrase in _FIRST_PERSON["comitative"]:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase) + "(?=" + _COMITATIVE_VERB_CLASS + ")"
        matches = re.findall(pattern, work)
        if matches:
            work = re.sub(pattern, "", work)
            cnt += len(matches)
    # 「我想」+ 动词锚定：仅删「我想」留动词（避免误删「我想你/我想家」）
    want_pattern = _NEG_LOOKBEHIND + "我想" + "(?=" + _FIRST_PERSON_INTENT_VERB_CLASS + ")"
    matches = re.findall(want_pattern, work)
    if matches:
        work = re.sub(want_pattern, "", work)
        cnt += len(matches)
    return work, cnt


def _rule_courtesy_boilerplate(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """客套 / 寒暄 / 礼貌冗余移除（explicit-only，不进 PRESETS）。

    - 仅当用户显式勾选（explicit=True）时生效；rules=None 路径永不触发，保障零回归。
    - 删除无信息量的客套噪声：招呼（你好/您好/在吗）、道歉（对不起/抱歉/不好意思/
      打扰了）、感谢（谢谢/感谢/辛苦了/麻烦了）、条件式客套求助（如果可以的话/
      如果方便的话）、结尾套话（仅供参考/不吝赐教/敬请谅解/如有问题/请知悉）。
    - 与 ``politeness`` 互补：politeness 处理「请/麻烦/劳烦/帮我」等指令语气词，
      本规则只收「纯礼貌套话」，二者可同开、互不替代、不重复计数（先删者移除后
      后者不再命中）。
    - 长词优先（``_COURTESY_PHRASES`` 已长→短排序）：「谢谢你」整体删，不残留孤立「你」。
    - 受保护片段（代码块/URL/行内代码）已由外层 ``_protect`` 冻结，本函数不触碰。
    """
    matches = _COURTESY_RE.findall(work)
    if matches:
        work = _COURTESY_RE.sub("", work)
        return work, len(matches)
    return work, 0


# 规则注册表：id -> fn（default_in_presets 仅供文档/自检）
RULE_REGISTRY: dict[str, dict] = {
    "politeness":        {"fn": _rule_politeness,        "default_in_presets": True},
    "first_person":      {"fn": _rule_first_person,      "default_in_presets": False},
    "courtesy_boilerplate": {"fn": _rule_courtesy_boilerplate, "default_in_presets": False},
    "role_prefix":       {"fn": _rule_role_prefix,       "default_in_presets": True},
    "empty_items":       {"fn": _rule_empty_items,       "default_in_presets": True},
    "duplicate_lines":   {"fn": _rule_duplicate_lines,   "default_in_presets": True},
    "blank_lines":       {"fn": _rule_blank_lines,       "default_in_presets": True},
    "meta_comment":      {"fn": _rule_meta_comment,      "default_in_presets": False},
    "hedging":           {"fn": _rule_hedging,           "default_in_presets": False},
    "redundant_adverbs": {"fn": _rule_redundant_adverbs, "default_in_presets": False},
    "examples_trim":     {"fn": _rule_examples_trim,     "default_in_presets": False},
    "logical_connector": {"fn": _rule_logical_connector, "default_in_presets": False},
    "filler_particles":  {"fn": _rule_filler_particles,  "default_in_presets": False},
    "duplicate_clauses":   {"fn": _rule_duplicate_clauses,   "default_in_presets": False},
    "punctuation_compress":{"fn": _rule_punctuation_compress,"default_in_presets": False},
    "punctuation_normalize":{"fn": _rule_punctuation_normalize,"default_in_presets": False},
    "semantic_compress":  {"fn": _rule_semantic_compress,  "default_in_presets": False},
}


def _resolve_rule_ids(rules, mode: str) -> tuple[list[str], str, bool]:
    """解析规则集与 aggressive_like（§3.3）。

    返回 (ordered_rule_ids, mode_used, aggressive_like)。
    - rules is None → 用 PRESETS[mode]，aggressive_like = (mode == "aggressive")。
    - rules 为 list → 仅留合法 id（∈ ALL_RULE_IDS）、去重、按 CANONICAL_ORDER 排序；
      空集合（全非法/空数组）→ 保底 ["blank_lines"]（保护 + 空行折叠）。
    """
    aggressive_like = (mode == "aggressive")
    if rules is None:
        ids = PRESETS.get(mode, PRESETS["balanced"])
        return ids, mode, aggressive_like

    valid = [r for r in rules if r in ALL_RULE_IDS]
    if not valid:
        return ["blank_lines"], mode, aggressive_like
    ordered = sorted(set(valid), key=lambda x: CANONICAL_ORDER.index(x))
    return ordered, mode, aggressive_like


def _tag(change: str, category: str, explicit: bool) -> str:
    """仅当显式下发 rules 时附加 [category] 标签（保障 P0-3 预设模式纯文本格式）。"""
    return change if not explicit else f"{change} [{category}]"


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def simplify_prompt(text: str, mode: str = "balanced", rules: list[str] | None = None,
                    semantic_threshold: float = _SEMANTIC_THRESHOLD_DEFAULT,
                    semantic_prune: bool = False,
                    personal_phrases: list[str] | None = None) -> dict:
    """简化通用 prompt 文本，返回含 token 节省统计的 dict。

    参数:
        text: 原始 prompt 文本。
        mode: ``"balanced"``（保守）或 ``"aggressive"``（激进）。
            同时承载 ``aggressive_like`` 语义（仅影响 role_prefix/politeness 的
            原 aggressive 专属子步骤：行内角色兜底 5.b / 单字「请」）。
        rules: 可选规则类别集合（元素为 ``ALL_RULE_IDS``）。
            - ``None`` → 按 ``mode`` 展开 ``PRESETS``（与 v2.5 逐字一致，P0-3）。
            - ``[]`` / 全非法 → 保底 ``["blank_lines"]``（仅保护 + 空行折叠）。
            - 合法非空 → 以该集合为准（可独立开关每类），不强制 ``blank_lines``。
        semantic_threshold: 仅当 ``rules`` 含 ``semantic_compress`` 时生效的近义判定阈值
            （余弦相似度 ≥ 阈值判语义重复）。默认 0.90，越界/非法静默回落默认（绝不 500）。
        semantic_prune: 仅当 ``rules`` 含 ``semantic_compress`` 时生效的重要性剪枝二级开关
            （默认 False）。embedding 不可用或后端非稠密时语义压缩整体静默跳过，输出不变。
        personal_phrases: 用户个性化口癖清单（如「请」「麻烦你」）。非 None 且非空时，
            在规则管线结束后额外消除这些短语（默认开启）。该层独立于规则注册表，不影响
            ``rules=None`` 零回归契约（仅当调用方显式传入 personal_phrases 时生效）。

    硬契约：``rules is None`` 时后端仅走 ``PRESETS``（5 基础类），``simplified_text`` 必须
    逐字等于 v2.5；任何新增行为（含 semantic_compress）不得改变该路径输出。

    返回 dict 键（结构不变，向后兼容）：
        original_text, simplified_text, original_tokens, simplified_tokens,
        tokens_saved, savings_pct, changes。
    """
    original = text if text is not None else ""
    original_tokens = count_tokens(original)

    if not original.strip():
        return {
            "original_text": "",
            "simplified_text": "",
            "original_tokens": 0,
            "simplified_tokens": 0,
            "tokens_saved": 0,
            "savings_pct": 0.0,
            "changes": [],
        }

    explicit = rules is not None
    rule_ids, mode_used, aggressive_like = _resolve_rule_ids(rules, mode)

    # 1) 保护：代码块 / URL / 行内代码 / 含填充字安全词
    protected: list[str] = []
    work = _protect(original, protected)
    work = _protect_words(work, protected, _PROTECT_WORDS)

    changes: list[str] = []

    # 2) 空列表项 + 重复指令（顺序与 v2.5 一致；各自可独立关闭）
    if "empty_items" in rule_ids:
        work, n = _rule_empty_items(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"删除 {n} 个空列表项", "empty_items", explicit))
    if "duplicate_lines" in rule_ids:
        work, n = _rule_duplicate_lines(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"合并 {n} 条重复指令", "duplicate_lines", explicit))
    # 2.1) evo2-8：跨句完全重复子句去重（方案 B，explicit-only，不进 PRESETS）
    if "duplicate_clauses" in rule_ids:
        work, n = _rule_duplicate_clauses(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处跨句重复子句", "duplicate_clauses", explicit))

    # 3) 空行折叠（首折，与 v2.5 顺序一致）
    if "blank_lines" in rule_ids:
        work = _rule_blank_lines(work, aggressive_like, explicit)[0]

    # 4.0) evo2-12：客套/寒暄冗余（explicit-only，不进 PRESETS；置 politeness 之前，
    #      使「感谢你/谢谢你」整体作为单元移除，避免 politeness 先拆「感谢」残留孤立「你」）
    if "courtesy_boilerplate" in rule_ids:
        work, n = _rule_courtesy_boilerplate(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处客套/寒暄冗余", "courtesy_boilerplate", explicit))

    # 4) 礼貌/冗余填充词
    if "politeness" in rule_ids:
        work, n = _rule_politeness(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处礼貌/冗余填充词", "politeness", explicit))

    # 4.1) evo2-11：第一人称自指冗余（explicit-only，不进 PRESETS；紧接 politeness 之后，
    #     使「请给我 X」在 aggressive 下先删「请」再删「给我」→ 最终「X」，符合深度清理 Q4）
    if "first_person" in rule_ids:
        work, n = _rule_first_person(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处第一人称自指标记", "first_person", explicit))

    # 5) 冗长角色前缀精简
    if "role_prefix" in rule_ids:
        work, n = _rule_role_prefix(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"精简 {n} 处角色描述", "role_prefix", explicit))

    # 6) v2.6 新增类别（仅显式勾选时进入；不在 PRESETS，故不影响零回归）
    if "meta_comment" in rule_ids:
        work, n = _rule_meta_comment(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处元评论/过渡句", "meta_comment", explicit))
    if "hedging" in rule_ids:
        work, n = _rule_hedging(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处弱语气词", "hedging", explicit))
    if "redundant_adverbs" in rule_ids:
        work, n = _rule_redundant_adverbs(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处冗余副词", "redundant_adverbs", explicit))
    if "examples_trim" in rule_ids:
        work, n = _rule_examples_trim(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"压缩 {n} 处过长示例", "examples_trim", explicit))

    # 7) evo2-7 新增类别（逻辑连接词 / 句末语气词；永不进 PRESETS）
    if "logical_connector" in rule_ids:
        work, n = _rule_logical_connector(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处逻辑/过渡连接词", "logical_connector", explicit))
    if "filler_particles" in rule_ids:
        work, n = _rule_filler_particles(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处句末语气助词", "filler_particles", explicit))
    # 8) evo2-8 新增类别（连续标点折叠；永不进 PRESETS，仅 explicit）
    if "punctuation_compress" in rule_ids:
        work, n = _rule_punctuation_compress(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"折叠 {n} 处多余连续标点", "punctuation_compress", explicit))
    # 8.0) evo2-10 新增类别（标点归一化：2+ 连续折叠 + 标点周围空格规整；永不进 PRESETS，仅 explicit）
    if "punctuation_normalize" in rule_ids:
        work, n = _rule_punctuation_normalize(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"归一化 {n} 处标点冗余", "punctuation_normalize", explicit))
    # 8.2) evo2-15 长文本增强（条件 hedge 剪枝 / 冗余枚举折叠；永不进 PRESETS，仅 explicit）
    if "condition_clause" in rule_ids:
        work, n = _rule_condition_clause(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"剪枝 {n} 处条件/保留语境 hedge", "condition_clause", explicit))
    if "redundant_enum" in rule_ids:
        work, n = _rule_redundant_enum(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"折叠 {n} 处冗余枚举项", "redundant_enum", explicit))
    # 8.1) evo2-9 新增类别（本地语义压缩；永不进 PRESETS，仅 explicit；embedding 不可用则跳过）
    if "semantic_compress" in rule_ids:
        th = _semantic_threshold_clamp(semantic_threshold)
        work, n = _rule_semantic_compress(
            work, aggressive_like, explicit, threshold=th, prune=bool(semantic_prune),
        )
        if n:
            changes.append(_tag(f"折叠 {n} 处语义重复句", "semantic_compress", explicit))

    # 7) 还原（先放回归位保护片段，再按 blank_lines 是否启用决定折叠策略）
    work = _restore(work, protected)
    # 7.0) 个性化口癖消除（独立于规则注册表，默认开启；仅当显式传入 personal_phrases 时生效）
    if personal_phrases:
        removed_p = 0
        for ph in personal_phrases:
            if not ph:
                continue
            cnt = work.count(ph)
            if cnt:
                work = work.replace(ph, "")
                removed_p += cnt
        if removed_p:
            work = re.sub(r" {2,}", " ", work)   # 消除移除后残留的多余空格
            changes.append(f"移除 {removed_p} 处个性化口癖")
    if "blank_lines" in rule_ids:
        # 启用：折叠连续空行 + 行首尾空白清理（v2.5 默认行为）
        work = _collapse_blank_lines(work).strip()
    else:
        # 显式关闭：仅整体 strip，保留内部空行（architect U7 / PRD P0-3 之外的行为）
        work = work.strip()

    simplified = work
    simplified_tokens = count_tokens(simplified)
    tokens_saved = max(0, original_tokens - simplified_tokens)
    savings_pct = (
        round(tokens_saved / original_tokens * 100, 1) if original_tokens else 0.0
    )

    if not changes:
        changes.append("无需变更")

    return {
        "original_text": original,
        "simplified_text": simplified,
        "original_tokens": original_tokens,
        "simplified_tokens": simplified_tokens,
        "tokens_saved": tokens_saved,
        "savings_pct": savings_pct,
        "changes": changes,
    }
