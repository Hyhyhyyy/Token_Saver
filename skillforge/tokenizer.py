"""Token 计量：优先使用 tiktoken(cl100k_base)，缺失时回退到字符启发式估算。"""
from __future__ import annotations

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_ENC.encode(text))

    BACKEND = "tiktoken/cl100k_base"
except ImportError:
    def count_tokens(text: str) -> int:
        if not text:
            return 0
        # 中文约 1.6 字符/token，英文约 4 字符/token 的混合启发式
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        other = len(text) - cjk
        return max(1, round(cjk / 1.6 + other / 4))

    BACKEND = "heuristic(chars/4)"
