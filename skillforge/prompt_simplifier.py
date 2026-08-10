"""Prompt 简化器（v2.5 核心新功能）：通用 prompt 文本压缩。

目标：在不破坏语义与代码结构的前提下，去除冗余礼貌用语、合并重复指令、
删除空列表项、精简冗长角色描述，并保留代码块（```...```）、行内代码、URL
与技术标识符。token 计数复用 ``skillforge.tokenizer.count_tokens``
（tiktoken cl100k_base；缺失时回退字符启发式）。

零新增 pip 依赖：仅 Python 标准库 + 现有 tokenizer。
"""
from __future__ import annotations

import re

from .tokenizer import count_tokens

# --------------------------------------------------------------------------- #
# 填充词表（按模式分档）
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
# 内部工具
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
    """归一化一行用于去重比较：去空白、去标点、小写。

    说明：Python 的 ``\\w`` 含 CJK，故 ``[^\\w]`` 之外的 CJK 字面会保留，
    仅去除中英文标点与空白，使「近 identical」的指令可比。
    """
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
    # 去除首尾多余空行
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _simplify_role(line: str, aggressive: bool) -> tuple[str, bool]:
    """行首冗长角色描述前缀精简。仅当整行以角色前缀开头时替换。

    balanced 与 aggressive 共用同一组前缀表（角色精简本身即安全动作）。
    """
    stripped = line.lstrip()
    for prefix, repl in _ROLE_PREFIXES:
        if stripped.startswith(prefix):
            return repl + stripped[len(prefix):], True
    return line, False


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def simplify_prompt(text: str, mode: str = "balanced") -> dict:
    """简化通用 prompt 文本，返回含 token 节省统计的 dict。

    参数:
        text: 原始 prompt 文本。
        mode: ``"balanced"``（保守）或 ``"aggressive"``（更激进地去冗余）。

    返回 dict 键：
        original_text, simplified_text, original_tokens, simplified_tokens,
        tokens_saved, savings_pct, changes。

    简化规则（通用 prompt，非 SKILL.md 专属）：
        - 去除首尾空白、折叠连续空行为至多 1 个；
        - 移除/削弱中英文礼貌填充词；
        - 合并同一 prompt 内重复（或近 identical）的指令为一条；
        - 删除空列表项 / 空编号项；
        - 在安全前提下精简冗长角色描述；
        - 保留代码块（```...```）、行内代码、URL 与技术标识符；
        - ``mode="aggressive"`` 在 balanced 基础上做更强裁剪。
    """
    original = text if text is not None else ""
    original_tokens = count_tokens(original)

    # 空输入：优雅返回全零 / 空串
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

    aggressive = (mode == "aggressive")
    changes: list[str] = []

    # 1) 保护：代码块 / URL / 行内代码 / 含填充字安全词
    protected: list[str] = []
    work = _protect(original, protected)
    work = _protect_words(work, protected, _PROTECT_WORDS)

    # 2) 行级处理：拆行 → 删空列表项 → 合并重复行
    lines = work.split("\n")
    kept_lines: list[str] = []
    empty_bullets = 0
    seen_norm: dict[str, int] = {}
    dup_removed = 0
    for line in lines:
        if _EMPTY_BULLET_RE.match(line):
            empty_bullets += 1
            continue
        norm = _norm_line(line)
        if norm:  # 仅非空行参与去重比较
            if norm in seen_norm:
                dup_removed += 1
                continue
            seen_norm[norm] = 1
        kept_lines.append(line)
    work = "\n".join(kept_lines)

    if empty_bullets:
        changes.append(f"删除 {empty_bullets} 个空列表项")
    if dup_removed:
        changes.append(f"合并 {dup_removed} 条重复指令")

    # 3) 折叠连续空行（≤1 个）并清理每行首尾空白
    work = _collapse_blank_lines(work)

    # 4) 移除填充词（中文 + 英文）
    cn_fillers = list(_CN_FILLERS_BALANCED)
    en_fillers = list(_EN_FILLERS_BALANCED)
    if aggressive:
        cn_fillers += _CN_FILLERS_AGGRESSIVE
        en_fillers += _EN_FILLERS_AGGRESSIVE

    filler_removed = 0
    # 英文：词级（大小写不敏感）整体移除
    for phrase in en_fillers:
        cnt = work.lower().count(phrase)
        if cnt:
            work = re.sub(r"(?i)" + re.escape(phrase), "", work)
            filler_removed += cnt
    # 中文：短语移除
    for phrase in cn_fillers:
        cnt = work.count(phrase)
        if cnt:
            work = work.replace(phrase, "")
            filler_removed += cnt
    # 中文单字「请」：仅当它后接汉字时移除（安全词已先行保护）
    if aggressive:
        cnt = len(re.findall(r"请(?=[一-鿿])", work))
        if cnt:
            work = re.sub(r"请(?=[一-鿿])", "", work)
            filler_removed += cnt

    if filler_removed:
        changes.append(f"移除 {filler_removed} 处礼貌/冗余填充词")

    # 5) 精简冗长角色描述（仅行首）
    role_hits = 0
    out_lines = []
    for line in work.split("\n"):
        new_line, hit = _simplify_role(line, aggressive)
        if hit:
            role_hits += 1
        out_lines.append(new_line)
    work = "\n".join(out_lines)
    if role_hits:
        changes.append(f"精简 {role_hits} 处角色描述")

    # 6) 清理：折叠空行 + 去首尾空白 + 还原占位符
    work = _collapse_blank_lines(work).strip()
    work = _restore(work, protected)
    # 还原后可能残留多余空行，再折叠一次
    work = _collapse_blank_lines(work).strip()

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
