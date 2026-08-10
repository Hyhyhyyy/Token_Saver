"""v2.5 Prompt 简化器：纯函数单元测试（无需 DB / 后端）。

覆盖：基础压缩降 token、空输入零值、aggressive 比 balanced 省更多、
代码块 / URL 受保护不被篡改。
"""
import pytest

from skillforge.prompt_simplifier import simplify_prompt

pytestmark = pytest.mark.a


def test_basic_reduces_tokens():
    text = (
        "请你帮我写一个函数。\n"
        "请务必使用 Python 实现。\n"
        "请确保代码有注释。\n"
    )
    r = simplify_prompt(text, mode="balanced")
    assert r["original_tokens"] > 0
    assert r["simplified_tokens"] < r["original_tokens"]
    assert r["tokens_saved"] > 0
    assert r["savings_pct"] > 0.0
    # 礼貌填充词已被去除
    assert "请务必" not in r["simplified_text"]
    assert "请确保" not in r["simplified_text"]
    assert "请你" not in r["simplified_text"]
    # 变更记录存在且可读
    assert isinstance(r["changes"], list) and r["changes"]


def test_empty_input_returns_zeros():
    r = simplify_prompt("", mode="balanced")
    assert r["original_text"] == ""
    assert r["simplified_text"] == ""
    assert r["original_tokens"] == 0
    assert r["simplified_tokens"] == 0
    assert r["tokens_saved"] == 0
    assert r["savings_pct"] == 0.0
    assert r["changes"] == []

    # 仅空白/空行同样视为空
    r2 = simplify_prompt("   \n\n  ", mode="aggressive")
    assert r2["original_tokens"] == 0
    assert r2["simplified_tokens"] == 0
    assert r2["changes"] == []


def test_aggressive_saves_more_than_balanced():
    verbose = (
        "You are a helpful assistant. "
        "I want you to just simply write a function. "
        "Please make sure to very carefully use Python. "
        "你是一个专业的助手。请尽量使用 Python。\n"
        "你是一个专业的助手。请尽量使用 Python。\n"  # 重复行 -> 合并
    )
    bal = simplify_prompt(verbose, mode="balanced")
    agg = simplify_prompt(verbose, mode="aggressive")
    # aggressive 至少不弱于 balanced，且应省更多 token
    assert agg["simplified_tokens"] <= bal["simplified_tokens"]
    assert agg["tokens_saved"] >= bal["tokens_saved"]
    # aggressive 特有裁剪生效
    assert "你是一个专业的" not in agg["simplified_text"]  # 角色精简
    assert "just" not in agg["simplified_text"].lower()     # just 被移除
    assert "very" not in agg["simplified_text"].lower()      # very 被移除


def test_preserves_code_blocks_and_urls():
    text = (
        "请帮我实现一个函数。\n"
        "示例如下：\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b  # 请保留这行注释\n"
        "```\n"
        "参考文档：https://example.com/docs?q=1 中的说明。\n"
    )
    r = simplify_prompt(text, mode="aggressive")
    out = r["simplified_text"]
    # 代码块整体保留
    assert "def add(a, b):" in out
    assert "return a + b" in out
    # 代码块内的「请保留」不应被删（受保护）
    assert "请保留这行注释" in out
    # URL 保留
    assert "https://example.com/docs?q=1" in out
    # 顶层「请帮我」被去除，但代码/URL 完好
    assert r["simplified_tokens"] < r["original_tokens"]
