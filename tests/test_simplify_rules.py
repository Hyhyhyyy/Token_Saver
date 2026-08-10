"""v2.6 新增可多选规则：逐类别开关、保护、边界、非法 id、U7 行为、aggressive_like。

锁定 P0 系列：新类别仅显式勾选时生效；rules=None 零回归（见 parity 测试）；
显式非空且不含 blank_lines 时不折叠内部空行（architect U7）。
"""
import pytest

from skillforge.prompt_simplifier import (
    simplify_prompt,
    ALL_RULE_IDS,
    PRESETS,
)

pytestmark = pytest.mark.a

BASE5 = PRESETS["balanced"]


def _text(rule_ids, text, mode="balanced"):
    return simplify_prompt(text, mode=mode, rules=rule_ids)


def test_all_rule_ids_exact():
    assert ALL_RULE_IDS == [
        "politeness", "role_prefix", "empty_items", "duplicate_lines",
        "blank_lines", "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
        "logical_connector", "filler_particles",
    ]


def test_presets_equal_v25_no_new_categories():
    # P0-3：PRESETS 不含任何 v2.6 新类别，且 balanced == aggressive
    assert PRESETS["balanced"] == BASE5
    assert PRESETS["aggressive"] == BASE5
    assert set(BASE5) == {
        "politeness", "role_prefix", "empty_items", "duplicate_lines", "blank_lines",
    }
    assert not (
        set(PRESETS["balanced"])
        & {"meta_comment", "hedging", "redundant_adverbs", "examples_trim"}
    )


def test_meta_comment_on_off():
    text = "需要注意的是，这个任务很简单。请开始吧。"
    on = _text(["meta_comment"], text)
    assert "需要注意的是" not in on["simplified_text"]
    off = _text([], text)  # 兜底 blank_lines
    assert "需要注意的是" in off["simplified_text"]


def test_hedging_removes_but_not_negated():
    text = "也许他会来，但其实不可能。"
    on = _text(["hedging"], text)
    assert "也许" not in on["simplified_text"]
    assert "不可能" in on["simplified_text"]  # 否定前瞻保护

    on2 = _text(["hedging"], "这件事或许可以，但或许不完全成立。")
    assert "或许" not in on2["simplified_text"]
    assert "不完全" in on2["simplified_text"]


def test_redundant_adverbs_off_negated():
    text = "这个功能非常强大，但逻辑不完全严谨。"
    on = _text(["redundant_adverbs"], text)
    assert "非常" not in on["simplified_text"]
    assert "不完全" in on["simplified_text"]  # 否定前瞻保护


def test_examples_trim_triggers_on_long_block():
    block = "例如：\n苹果\n香蕉\n橙子\n葡萄\n西瓜\n芒果\n"
    on = _text(["examples_trim"], block)
    out = on["simplified_text"]
    assert "示例已压缩" in out
    assert "共 6 行" in out
    assert "苹果" in out and "香蕉" in out and "橙子" in out


def test_examples_trim_skips_short_block():
    block = "例如：\n苹果\n香蕉\n"
    on = _text(["examples_trim"], block)
    assert "示例已压缩" not in on["simplified_text"]
    assert "苹果" in on["simplified_text"] and "香蕉" in on["simplified_text"]


def test_examples_trim_preserves_protect_token_lines():
    # 代码块作为保护 token，即便排在「前 3 行」之后也必须保留
    block = (
        "示例如下：\n"
        "正常说明行1\n正常说明行2\n正常说明行3\n"
        "```python\ncode_here = 1\n```\n"
        "正常说明行4\n正常说明行5\n正常说明行6\n"
    )
    on = _text(["examples_trim"], block)
    out = on["simplified_text"]
    assert "code_here = 1" in out  # 保护 token 行被保留
    assert "示例已压缩" in out


def test_politeness_off_keeps_fillers():
    text = "请你帮我写代码。"
    off = _text(["blank_lines"], text)  # 仅 blank_lines，关掉 politeness
    assert "请你" in off["simplified_text"]
    on = _text(["politeness"], text)
    assert "请你" not in on["simplified_text"]


def test_role_prefix_off_keeps_role():
    text = "你是一个专业的助手，负责回答问题。"
    off = _text(["blank_lines"], text)
    assert "你是一个专业的" in off["simplified_text"]
    on = _text(["role_prefix"], text)
    assert "你是一个专业的" not in on["simplified_text"]


def test_empty_items_off_keeps_empty_bullets():
    text = "- 项目A\n- \n- 项目B\n"
    off = _text(["blank_lines"], text)
    # 空 bullet 行仍在（仅被去尾随空格），未被 empty_items 删除 → 共 3 行
    assert off["simplified_text"].count("\n") == 2
    on = _text(["empty_items"], text)
    # 空 bullet 被删除 → 共 2 行
    assert on["simplified_text"].count("\n") == 1


def test_duplicate_lines_off_keeps_dups():
    text = "步骤：打开。\n步骤：打开。\n"
    off = _text(["blank_lines"], text)
    assert off["simplified_text"].count("步骤：打开。") == 2
    on = _text(["duplicate_lines"], text)
    assert on["simplified_text"].count("步骤：打开。") == 1


def test_invalid_rule_id_ignored_falls_back_to_blank_lines():
    text = "请你帮忙。\n\n\n正文\n"
    invalid = _text(["not_a_rule", "another_fake"], text)
    only_blank = _text(["blank_lines"], text)
    assert invalid["simplified_text"] == only_blank["simplified_text"]
    # 礼貌词未被移除（非法 id 不触发任何实际规则，仅 blank_lines 生效）
    assert "请你" in invalid["simplified_text"]


def test_rules_empty_falls_back_to_blank_lines():
    text = "请你帮忙。\n\n\n正文\n"
    empty = _text([], text)
    only_blank = _text(["blank_lines"], text)
    assert empty["simplified_text"] == only_blank["simplified_text"]
    assert "\n\n\n" not in empty["simplified_text"]


def test_u7_explicit_without_blank_lines_preserves_blanks():
    # architect U7：显式非空且不含 blank_lines → 内部连续空行不折叠
    text = "第一段\n\n\n\n第二段"
    no_blank = _text(["politeness"], text)  # 不含 blank_lines
    assert "\n\n\n\n" in no_blank["simplified_text"]
    with_blank = _text(["blank_lines"], text)
    assert "\n\n\n\n" not in with_blank["simplified_text"]


def test_aggressive_like_via_mode_single_qing():
    # 契约变更（evo2-7）：单字「请」在 aggressive 模式 或 explicit 路径（下发 rules）均移除；
    # 仅 rules=None（explicit=False，≡ v2.5）的 balanced 保留。
    text = "请开始写代码。请你吃饭。"
    # rules=None balanced（v2.5 等价）：单字「请」保留
    none_bal = simplify_prompt(text, mode="balanced")
    assert "请开始" in none_bal["simplified_text"]
    # explicit balanced（前端默认下发 rules，explicit=True）：单字「请」移除（默认更强）
    exp_bal = simplify_prompt(text, mode="balanced", rules=["politeness"])
    assert "请开始" not in exp_bal["simplified_text"]
    # aggressive 模式（rules=None）同样移除单字「请」
    agg = simplify_prompt(text, mode="aggressive")
    assert "请开始" not in agg["simplified_text"]


def test_aggressive_like_via_mode_inline_role():
    text = "Here is the task. 你是一个专业的助手，负责回答。"
    bal = _text(["role_prefix"], text, mode="balanced")
    agg = _text(["role_prefix"], text, mode="aggressive")
    assert "你是一个专业的" in bal["simplified_text"]      # 行内不删
    assert "你是一个专业的" not in agg["simplified_text"]  # 行内兜底删


# --------------------------------------------------------------------------- #
# 边界补充（v2.6 QA 审查发现的薄弱点 / 复现用例）
# --------------------------------------------------------------------------- #
def test_redundant_adverbs_preserves_negated_compound_phrases():
    """否定前瞻必须是「短语级」而非仅紧贴前字。

    约束要求 hedging/redundant_adverbs 带 (?<!不)(?<!没)(?<!别) 避免误删
    「不可能/不完全」等。当前实现仅检查副词『紧贴前一字』，导致「不可能完全 /
    并没有完全」这类否定结构中的「完全」被误删，改变语义（not completely → not）。
    """
    text = "这不可能完全准确，且并没有完全解决。"
    on = _text(["redundant_adverbs"], text)
    assert "完全" in on["simplified_text"]  # 不得因否定结构隔字而误删


def test_examples_trim_keeps_real_lines_despite_inline_code_block():
    """示例块内若含受保护代码块，不得因代码块占用「前 3 行」名额而裁掉真实示例。

    设：示例引导词后紧跟一个代码块（变为单 token 行），再跟 4 行真实示例。
    压缩时应保留全部真实示例行 + 代码块，绝不能丢失用户内容。
    """
    block = (
        "例如：\n"
        "```python\nx = 1\n```\n"
        "苹果\n香蕉\n橙子\n葡萄\n"
    )
    on = _text(["examples_trim"], block)
    out = on["simplified_text"]
    assert "x = 1" in out  # 保护 token 保留
    # 真实示例行不得因代码块占位而被丢弃
    assert "苹果" in out and "香蕉" in out and "橙子" in out and "葡萄" in out


def test_examples_trim_threshold_boundary():
    """示例压缩阈值边界：恰好 3 行不压缩，恰好 4 行压缩（锁定边界行为）。"""
    three = "例如：\n苹果\n香蕉\n橙子\n"
    r3 = _text(["examples_trim"], three)
    assert "示例已压缩" not in r3["simplified_text"]
    assert "苹果" in r3["simplified_text"] and "香蕉" in r3["simplified_text"] and "橙子" in r3["simplified_text"]

    four = "例如：\n苹果\n香蕉\n橙子\n葡萄\n"
    r4 = _text(["examples_trim"], four)
    assert "示例已压缩" in r4["simplified_text"]
    assert "共 4 行" in r4["simplified_text"]


# --------------------------------------------------------------------------- #
# evo2-7 新增：逻辑连接词 / 句末语气词 / 显式礼貌词强化 / 弱语气词强化
# --------------------------------------------------------------------------- #
def test_logical_connector_removes_free_connectors():
    """游离连接词被移除，但不删指令性内容。"""
    text = "因此，我们需要先读取配置。但是请注意端口。然后启动服务。"
    on = _text(["logical_connector"], text)
    out = on["simplified_text"]
    assert "因此" not in out
    assert "但是" not in out
    assert "然后" not in out
    # 保留关键动作/参数
    assert "读取配置" in out
    assert "端口" in out
    assert "启动服务" in out


def test_logical_connector_keeps_conditional_and_ordered_list():
    """条件标记（如果/则/否则）不删；有序列表行内序列词受局部哨兵保护不删。"""
    # 条件结构保留
    cond = "如果文件存在，则读取它，否则创建新文件。"
    rc = _text(["logical_connector"], cond)
    assert "如果" in rc["simplified_text"]
    assert "则" in rc["simplified_text"]
    assert "否则" in rc["simplified_text"]

    # 有序列表行内序列词保护
    lst = "1. 首先打开文件。\n2. 然后读取内容。\n3. 最后保存。"
    rl = _text(["logical_connector"], lst)
    out = rl["simplified_text"]
    assert "首先" in out
    assert "然后" in out
    assert "最后" in out
    # 编号列表结构保留
    assert "1." in out and "2." in out and "3." in out


def test_logical_connector_negated_preserved():
    """否定前瞻保护：「不因此」不得误删为「不」。"""
    text = "我们不因此才失败的。"
    on = _text(["logical_connector"], text)["simplified_text"]
    assert "不因此" in on


def test_logical_connector_off_keeps_connectors():
    """规则关闭时连接词保留。"""
    text = "因此我们需要启动服务。"
    off = _text(["blank_lines"], text)
    assert "因此" in off["simplified_text"]


def test_filler_particles_removes_sentence_final():
    """句末语气助词移除；「吗」保留（疑问句意图）。"""
    text = "你帮我看看这个啊。它可以运行吗？请你确认嘛。"
    on = _text(["filler_particles"], text)
    out = on["simplified_text"]
    assert "啊" not in out
    assert "嘛" not in out
    # 「吗」不在移除集，疑问句保留
    assert "吗" in out


def test_filler_particles_keeps_mid_sentence():
    """句中语气助词谨慎不删。"""
    text = "嗯，这个呢需要通过测试。"
    on = _text(["filler_particles"], text)
    # 「呢」句中不删（无句末终结符紧随）
    assert "呢" in on["simplified_text"]


def test_filler_particles_negated_preserved():
    """否定前瞻保护：「不啊→不」不得误删。"""
    text = "这并不啊。"  # 构造否定紧贴语气词
    on = _text(["filler_particles"], text)
    assert "不啊" in on["simplified_text"]


def test_filler_particles_off_keeps():
    """规则关闭时语气词保留。"""
    text = "好的啊。"
    off = _text(["blank_lines"], text)
    assert "啊" in off["simplified_text"]


def test_politeness_explicit_only():
    """扩展礼貌词仅 explicit=True（下发 rules）时叠加；rules=None 不删。"""
    text = "请你帮我写代码，可以吗？"
    none = simplify_prompt(text, mode="balanced")  # rules=None → explicit=False
    exp = simplify_prompt(text, mode="balanced", rules=list(BASE5))  # explicit=True
    # rules=None 保留扩展礼貌词（不删「帮我」）
    assert "帮我" in none["simplified_text"]
    # 显式路径叠加扩展集 → 删除「帮我」
    assert "帮我" not in exp["simplified_text"]
    # 单字「请」在显式 balanced 也删除；rules=None 保留
    assert "请开始" in simplify_prompt("请开始写。", mode="balanced")["simplified_text"]
    assert "请开始" not in simplify_prompt("请开始写。", mode="balanced", rules=list(BASE5))["simplified_text"]


def test_hedging_strengthened():
    """hedging 强化：多字安全词（应该/估计/难免/基本上…）被移除，单字「应」不误伤。"""
    text = "你应该估计一下，难免出错，基本上可行。应用此配置响应请求。"
    on = _text(["hedging"], text)
    out = on["simplified_text"]
    assert "应该" not in out
    assert "估计" not in out
    assert "难免" not in out
    assert "基本上" not in out
    # 单字「应」刻意排除：应用 / 响应 不得被误删
    assert "应用" in out
    assert "响应" in out


def test_new_rule_ids_registered_not_in_presets():
    """两个新类别已注册，但永不进入 PRESETS（保障 rules=None ≡ v2.5）。"""
    from skillforge.prompt_simplifier import RULE_REGISTRY, PRESETS
    assert "logical_connector" in RULE_REGISTRY
    assert "filler_particles" in RULE_REGISTRY
    for preset_rules in PRESETS.values():
        assert "logical_connector" not in preset_rules
        assert "filler_particles" not in preset_rules

