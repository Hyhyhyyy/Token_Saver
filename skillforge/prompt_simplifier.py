"""Prompt 简化器（v2.6 重构）：通用 prompt 文本压缩 + 可多选规则配置。

目标：在不破坏语义与代码结构的前提下，按用户勾选的「规则类别」做无损裁剪。
保留 v2.5 的全部保护能力（代码块 / 行内代码 / URL / 含「请」安全词冻结）。

设计（见 docs/arch-evo2-6.md）：
- 规则注册表 ``RULE_REGISTRY`` + 预设 ``PRESETS`` + 单一真源 ``ALL_RULE_IDS``。
- ``simplify_prompt(text, mode, rules)`` 改为管道：解析 rules/预设 → 保护 →
  按 ``CANONICAL_ORDER`` 顺序执行启用类别 → 还原 → 统计。
- **零回归硬指标**：``rules is None`` 时 ``PRESETS`` 逐字等于 v2.5 行为
  （balanced/aggressive 输出与旧版字符串相等）。新类别（meta_comment / hedging /
  redundant_adverbs / examples_trim / logical_connector / filler_particles）仅当用户
  显式勾选（下发 ``rules``）时生效，不进 ``PRESETS``，故老 API 调用方行为不变。

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

from .tokenizer import count_tokens

# --------------------------------------------------------------------------- #
# 规则 id 单一真源（导出，前端 checkbox 与之严格对应）
# --------------------------------------------------------------------------- #
ALL_RULE_IDS: list[str] = [
    "politeness", "role_prefix", "empty_items", "duplicate_lines",
    "blank_lines", "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
    "logical_connector", "filler_particles",
]

# 类别执行顺序：前 5 位与 v2.5 执行顺序逐字一致，保障零回归（P0-3）。
CANONICAL_ORDER: list[str] = [
    "empty_items", "duplicate_lines", "blank_lines",
    "politeness", "role_prefix",
    "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
    "logical_connector", "filler_particles",
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
_HEDGING += [
    "应该", "估计", "想必", "多半", "八成", "兴许", "难免", "基本上", "大体上",
]


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
    """元评论 / 过渡句短语级移除（不破坏主干）。"""
    cnt = 0
    for phrase in _META_COMMENT:
        c = work.count(phrase)
        if c:
            work = work.replace(phrase, "")
            cnt += c
    return work, cnt


def _rule_hedging(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """弱语气 / 不确定性词移除（带否定前瞻，避免误伤「不可能/不完全/并没有完全」）。"""
    cnt = 0
    for phrase in _HEDGING:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase)
        matches = re.findall(pattern, work)
        if matches:
            work = re.sub(pattern, "", work)
            cnt += len(matches)
    return work, cnt


def _rule_redundant_adverbs(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    """冗余副词 / 强调移除（带否定前瞻，避免误伤「不完全/并没有完全」等）。"""
    cnt = 0
    for phrase in _REDUNDANT_ADV:
        pattern = _NEG_LOOKBEHIND + re.escape(phrase)
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
    # 1) 有序列表行：用局部哨兵保护行内序列词
    local_store: list[str] = []
    lines = work.split("\n")
    for i, line in enumerate(lines):
        if _ORDERED_LIST_LINE_RE.match(line):
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


# 规则注册表：id -> fn（default_in_presets 仅供文档/自检）
RULE_REGISTRY: dict[str, dict] = {
    "politeness":        {"fn": _rule_politeness,        "default_in_presets": True},
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
def simplify_prompt(text: str, mode: str = "balanced", rules: list[str] | None = None) -> dict:
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

    # 3) 空行折叠（首折，与 v2.5 顺序一致）
    if "blank_lines" in rule_ids:
        work = _rule_blank_lines(work, aggressive_like, explicit)[0]

    # 4) 礼貌/冗余填充词
    if "politeness" in rule_ids:
        work, n = _rule_politeness(work, aggressive_like, explicit)
        if n:
            changes.append(_tag(f"移除 {n} 处礼貌/冗余填充词", "politeness", explicit))

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

    # 7) 还原（先放回归位保护片段，再按 blank_lines 是否启用决定折叠策略）
    work = _restore(work, protected)
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
