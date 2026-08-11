"""evo2-15 长文本增强回归 + 改进测试（ASCII 安全：中文用 \\u 转义，规避写入编码问题）。

覆盖：
  1. 零回归：rules=None 路径对本段长文本输出逐字等于输入（5 基础类无命中）。
  2. 改进：新 aggressive 预设（含 condition_clause + redundant_enum）显著压缩长文本，
     且关键冗余被正确消除（再清洗 / 操作 / 真的可以实现的话 …）。
  3. 健壮性：MCP/skill、文件操作 等合法枚举不被破坏。
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skillforge.prompt_simplifier import simplify_prompt, ALL_RULE_IDS

USER_TEXT = (
    "\u6240\u4ee5\u8fd9\u4e2a\u9879\u76ee\u662f\u4e00\u4e2a\u4f1a\u914d\u5408\u63a5\u5165\u7684\u5927\u6a21\u578b\u7684"
    "MCP\u8fd8\u662f\u53ef\u8c03\u7528\u7684skill\uff1f\u662f\u4e0d\u662f\u9700\u8981\u521b\u5efa\u4e00\u4e2a\u672c"
    "\u9879\u76ee\u5185\u7684\u7279\u5b9a\u76ee\u5f55\uff0c\u7136\u540e\u7528\u6237\u60f3\u8981\u7b80\u5316\u7684skill"
    "\u90fd\u653e\u5230\u91cc\u9762\uff0c\u53ea\u8981\u653e\u5230\u91cc\u9762\u7684skill\u5c31\u4f1a\u88ab\u8bc6\u522b"
    "\u7136\u540e\u53ef\u4ee5\u8fdb\u884c\u6e05\u6d17/\u8fd8\u539f/\u518d\u6e05\u6d17/\u8ffd\u8e2a\u53d8\u66f4\u5386\u7a0b"
    "\u64cd\u4f5c\uff0c\u4eff\u771f\u6c99\u76d8\u5220\u9664\u5427\u53ef\u4ee5\u4e0d\u8981\uff0c\u51b2\u7a81\u68c0\u6d4b"
    "\u771f\u7684\u53ef\u4ee5\u5b9e\u73b0\u7684\u8bdd\u53ef\u4ee5\u4fdd\u7559\uff0c\u6570\u636e\u770b\u677f\u6709\u5145"
    "\u8db3\u771f\u5b9e\u4f9d\u636e\u7684\u8bdd\u53ef\u4ee5\u4fdd\u7559\u3002\u8fdb\u5316\u7684\u90e8\u5206\uff0c\u7528"
    "\u6237\u53ef\u80fd\u770b\u4e0d\u61c2\u9700\u8981\u5e72\u4ec0\u4e48\uff0c\u6539\u6210\u4e2a\u6027\u5316\uff0c\u7136"
    "\u540e\u8ba9\u7528\u6237\u5199\u5165\u81ea\u5df1\u53ef\u80fd\u4f1a\u767d\u6d88\u8017token\u4f46\u5f88\u5e38\u4f7f"
    "\u7528\u7684\u53e3\u7656\u6bd4\u5982\u8bf7\u4e4b\u7c7b\u7684\uff0c\u4e4b\u540e\u8fd9\u4e9b\u90fd\u9ed8\u8ba4\u6d88"
    "\u9664\u6389\uff0c\u5148\u505a\u8fd9\u4e00\u4e2a\u529f\u80fd\u3002"
)

NEW_AGGRESSIVE = [
    "politeness", "role_prefix", "empty_items", "duplicate_lines", "blank_lines",
    "meta_comment", "filler_particles", "duplicate_clauses", "punctuation_compress",
    "punctuation_normalize", "condition_clause", "redundant_enum",
    "first_person", "courtesy_boilerplate", "hedging", "redundant_adverbs",
    "examples_trim", "logical_connector",
]


def test_zero_regression_rules_none_unchanged():
    """rules=None 必须逐字等于输入（5 基础类对此密集需求散文无命中）。"""
    r = simplify_prompt(USER_TEXT, mode="balanced", rules=None)
    assert r["simplified_text"] == USER_TEXT
    assert r["tokens_saved"] == 0


def test_evo15_longtext_meaningful_compression():
    """新 aggressive 预设应显著压缩长文本，且关键冗余被消除。"""
    r = simplify_prompt(USER_TEXT, mode="aggressive", rules=NEW_AGGRESSIVE)
    out = r["simplified_text"]
    # 关键冗余消除断言
    assert "\u518d\u6e05\u6d17" not in out, "再清洗 应被折叠"
    assert "\u771f\u7684\u53ef\u4ee5\u5b9e\u73b0\u7684\u8bdd" not in out, "条件 hedge 应被剪枝"
    assert "\u6709\u5145\u8db3\u771f\u5b9e\u4f9d\u636e\u7684\u8bdd" not in out, "条件 hedge 应被剪枝"
    # 不应破坏合法 token 与枚举
    assert "MCP" in out and "skill" in out
    # 末项「操作」冗余尾应剥除
    assert "\u8ffd\u8e2a\u53d8\u66f4\u5386\u7a0b\u64cd\u4f5c" not in out
    # 压缩幅度应明显大于旧上限（旧全规则仅 ~5%）
    assert r["savings_pct"] >= 10.0, f"节省应 >=10%，实际 {r['savings_pct']}%"


def test_enum_dedup_focused():
    s = "\u8fdb\u884c\u6e05\u6d17/\u8fd8\u539f/\u518d\u6e05\u6d17/\u8ffd\u8e2a\u53d8\u66f4\u5386\u7a0b\u64cd\u4f5c"
    r = simplify_prompt(s, mode="aggressive", rules=["redundant_enum"])
    assert r["simplified_text"] == "\u8fdb\u884c\u6e05\u6d17/\u8fd8\u539f/\u8ffd\u8e2a\u53d8\u66f4\u5386\u7a0b"
    assert "\u518d\u6e05\u6d17" not in r["simplified_text"]


def test_caveat_hedge_focused():
    s = "\u51b2\u7a81\u68c0\u6d4b\u771f\u7684\u53ef\u4ee5\u5b9e\u73b0\u7684\u8bdd\u53ef\u4ee5\u4fdd\u7559"
    r = simplify_prompt(s, mode="aggressive", rules=["condition_clause"])
    assert r["simplified_text"] == "\u51b2\u7a81\u68c0\u6d4b\u53ef\u4ee5\u4fdd\u7559"


def test_legit_enum_survives():
    """MCP/skill 与 文件操作 不应被枚举折叠破坏。"""
    s = "\u8bf7\u652f\u6301\u6587\u4ef6\u64cd\u4f5c\u3001\u7f51\u7edc\u8bf7\u6c42\u548cMCP/skill\u7684\u8bc6\u522b\u3002"
    r = simplify_prompt(s, mode="aggressive", rules=NEW_AGGRESSIVE)
    assert "MCP/skill" in r["simplified_text"]
    assert "\u6587\u4ef6\u64cd\u4f5c" in r["simplified_text"]


def test_new_rule_ids_registered():
    assert "condition_clause" in ALL_RULE_IDS
    assert "redundant_enum" in ALL_RULE_IDS
