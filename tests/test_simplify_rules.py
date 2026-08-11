"""v2.6 新增可多选规则：逐类别开关、保护、边界、非法 id、U7 行为、aggressive_like。

锁定 P0 系列：新类别仅显式勾选时生效；rules=None 零回归（见 parity 测试）；
显式非空且不含 blank_lines 时不折叠内部空行（architect U7）。
"""
import pytest

from skillforge.prompt_simplifier import (
    simplify_prompt,
    ALL_RULE_IDS,
    PRESETS,
    _rule_semantic_compress,
    _semantic_threshold_clamp,
)

pytestmark = pytest.mark.a

BASE5 = PRESETS["balanced"]


def _text(rule_ids, text, mode="balanced"):
    return simplify_prompt(text, mode=mode, rules=rule_ids)


def test_all_rule_ids_exact():
    assert ALL_RULE_IDS == [
        "politeness", "first_person", "courtesy_boilerplate", "role_prefix", "empty_items", "duplicate_lines",
        "duplicate_clauses", "blank_lines", "meta_comment", "hedging",
        "redundant_adverbs", "examples_trim", "logical_connector",
        "filler_particles", "punctuation_compress", "punctuation_normalize",
        "condition_clause", "redundant_enum", "semantic_compress",
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
    """hedging 强化：多字安全词（估计/难免/基本上…）被移除，单字「应」不误伤。

    evo2-11 深化（P0-3）：「应该」已从 hedging 移除——指令语境（你应该返回JSON）
    是强约束而非弱语气，必须保留，不得误删。
    """
    text = "你应该估计一下，难免出错，基本上可行。应用此配置响应请求。"
    on = _text(["hedging"], text)
    out = on["simplified_text"]
    assert "应该" in out          # 强约束保护：保留
    assert "估计" not in out
    assert "难免" not in out
    assert "基本上" not in out
    # 单字「应」刻意排除：应用 / 响应 不得被误删
    assert "应用" in out
    assert "响应" in out


def test_hedging_keeps_yinggai_constraint():
    """evo2-11 深化：「你应该/模型应该」等指令强约束的「应该」必须保留。"""
    assert _text(["hedging"], "你应该返回 JSON 结果。")["simplified_text"] == "你应该返回 JSON 结果。"
    assert _text(["hedging"], "模型应该先验证输入再执行。")["simplified_text"] == "模型应该先验证输入再执行。"
    # 弱语气「应该」在口语闲聊中仍删（非指令语境，但当前规则不区分，统一保留「应该」）
    # 故此处仅守护"指令语境不误删"这一红线。


def test_new_rule_ids_registered_not_in_presets():
    """v2.6/v2.8/v2.10/v2.11/v2.12 新类别均已在注册表，但永不进入 PRESETS（保障 rules=None ≡ v2.5）。"""
    from skillforge.prompt_simplifier import RULE_REGISTRY, PRESETS
    for rid in ("first_person", "courtesy_boilerplate", "logical_connector", "filler_particles", "duplicate_clauses",
                "punctuation_compress", "punctuation_normalize"):
        assert rid in RULE_REGISTRY
    for preset_rules in PRESETS.values():
        assert "first_person" not in preset_rules
        assert "courtesy_boilerplate" not in preset_rules
        assert "logical_connector" not in preset_rules
        assert "filler_particles" not in preset_rules
        assert "duplicate_clauses" not in preset_rules
        assert "punctuation_compress" not in preset_rules
        assert "punctuation_normalize" not in preset_rules


# ---------- v2.8 新增类别（duplicate_clauses / punctuation_compress，均 explicit-only） ----------


def test_duplicate_clause_dedup_explicit_only():
    """未显式勾选（rules=None → PRESETS）时绝不触发跨句去重。

    rules=None 仍会跑 base5（如礼貌词删除「请确保」），但 duplicate_clauses 前缀去重不应发生；
    故与显式 base5 结果逐字一致，且「并校验字段」前缀保留。
    """
    text = "请确保输出 JSON。请确保输出 JSON 并校验字段。"
    out_none = simplify_prompt(text, rules=None)["simplified_text"]
    out_base5 = simplify_prompt(text, rules=list(BASE5))["simplified_text"]
    assert out_none == out_base5
    assert "并校验字段" in out_none


def test_duplicate_clause_keeps_shared_verb():
    """勾选后：跨句完全重复子句去重（长句前缀）。"""
    text = "请确保输出 JSON。请确保输出 JSON 并校验字段。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == "请确保输出 JSON。并校验字段。"


def test_duplicate_clause_terminal_word_no_overdeletion():
    """勾选后：句末尾词去重已移除（防误删关键名词），「总结…就是总结」保持不变。"""
    text = "总结一下，简单来说就是总结。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == text


def test_duplicate_clause_whole_sentence():
    """勾选后：整句重复（≥10 CJK）被去重。"""
    text = "我们要坚持长期主义并持续投入研发与生态建设。我们要坚持长期主义并持续投入研发与生态建设。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == "我们要坚持长期主义并持续投入研发与生态建设。"


def test_duplicate_clause_keeps_distinct_files():
    """不同文件引用不误删（尾词在前文未以相同形态出现）。"""
    text = "删除 config.py 中的 retry 配置。删除 output.log 中的错误行。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == text


# ---------- v2.8 Round-2：QA 严过关报告的 3 个源码 bug 回归锁 ----------


def test_duplicate_clause_short_exact_dup():
    """BUG-2 回归：短句精确重复（<10 CJK）应干净去重为单句，不得残留 。。"""
    text = "请提取超时请求。请提取超时请求。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == "请提取超时请求。"


def test_duplicate_clause_negation_dup():
    """BUG-3 回归：否定句精确重复应保留语义且不得产生 。。"""
    text = "没有重复。没有重复。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == "没有重复。"


def test_duplicate_clause_keeps_object_noun():
    """BUG-1 回归：句末关键名词（报告）不得被误删。"""
    text = "报告应包含所有字段。字段排序后导出报告。"
    out = _text(["duplicate_clauses"], text)
    assert out["simplified_text"] == text
    assert "导出报告" in out["simplified_text"]


def test_punctuation_compress_folds_triple():
    """勾选后：3+ 连续 ？！。 折叠为单字符。"""
    assert _text(["punctuation_compress"], "真的吗？？？")["simplified_text"] == "真的吗？"
    assert _text(["punctuation_compress"], "太棒了！！！")["simplified_text"] == "太棒了！"


def test_punctuation_compress_keeps_double():
    """双连标点（！？。各 2 个）必须原样保留。"""
    assert _text(["punctuation_compress"], "好的！！")["simplified_text"] == "好的！！"
    assert _text(["punctuation_compress"], "真的吗？？")["simplified_text"] == "真的吗？？"


def test_punctuation_compress_keeps_semantic():
    """省略号 …… 与破折号 —— 不在折叠集内，必须保留。"""
    assert _text(["punctuation_compress"], "他说……")["simplified_text"] == "他说……"
    assert _text(["punctuation_compress"], "这是重点——记牢")["simplified_text"] == "这是重点——记牢"


def test_punctuation_compress_keeps_code():
    """代码/行内代码内的标点受冻结保护，不被折叠。"""
    text = "运行 `exit ???` 后重试。"
    out = _text(["punctuation_compress"], text)
    assert "exit ???" in out["simplified_text"]


def test_punctuation_compress_explicit_only():
    """未显式勾选时不折叠。"""
    text = "真的吗？？？"
    out = simplify_prompt(text, rules=None)
    assert out["simplified_text"] == text


# ---------- v2.10 新增类别（punctuation_normalize，explicit-only） ----------


def test_punctuation_normalize_folds_double():
    """勾选后：2+ 连续相同 CJK 标点折叠为单个（与 punctuation_compress 互补）。"""
    assert _text(["punctuation_normalize"], "真的吗？？")["simplified_text"] == "真的吗？"
    assert _text(["punctuation_normalize"], "太棒了！！")["simplified_text"] == "太棒了！"
    # 不同标点相邻不互折
    assert _text(["punctuation_normalize"], "好的？。？")["simplified_text"] == "好的？。？"


def test_punctuation_normalize_folds_long_run():
    """勾选后：任意长度（3/5）连续相同标点均折叠为单个（验证整段折叠，无残留）。"""
    assert _text(["punctuation_normalize"], "？？？")["simplified_text"] == "？"
    assert _text(["punctuation_normalize"], "！！！！！")["simplified_text"] == "！"


def test_punctuation_normalize_trims_space():
    """勾选后：标点紧邻的 ASCII 空格（前/后/双侧）被删除。"""
    assert _text(["punctuation_normalize"], "你好 ， 世界")["simplified_text"] == "你好，世界"
    assert _text(["punctuation_normalize"], "请回答 ，")["simplified_text"] == "请回答，"
    assert _text(["punctuation_normalize"], "， 好的")["simplified_text"] == "，好的"


def test_punctuation_normalize_keeps_single_and_semantic():
    """单标点、省略号 ……、破折号 —— 不在归一化集内，必须保留。"""
    assert _text(["punctuation_normalize"], "你好，世界。")["simplified_text"] == "你好，世界。"
    assert _text(["punctuation_normalize"], "他说……")["simplified_text"] == "他说……"
    assert _text(["punctuation_normalize"], "这是重点——记牢")["simplified_text"] == "这是重点——记牢"


def test_punctuation_normalize_keeps_code():
    """代码/行内代码内的标点受冻结保护，不被归一化。"""
    text = "运行 `exit ，，` 后重试。"
    out = _text(["punctuation_normalize"], text)
    assert "exit ，，" in out["simplified_text"]


def test_punctuation_normalize_explicit_only():
    """未显式勾选（rules=None → PRESETS）时不归一化——保障 rules=None ≡ v2.5。"""
    text = "好的？？ 哈 ， 啦。"
    out = simplify_prompt(text, rules=None)
    assert out["simplified_text"] == text


# ---------- v2.11 新增类别（first_person 自指冗余 + 现有规则深化；均 explicit-only） ----------


def test_first_person_removes_benefit_and_intent():
    """勾选后：第一人称自指标记被移除（给我/和我/依我看/我想+动词）。"""
    assert _text(["first_person"], "请给我写个 Python 爬虫。")["simplified_text"] == "请写个 Python 爬虫。"
    assert _text(["first_person"], "和我确认下日程安排。")["simplified_text"] == "确认下日程安排。"
    assert _text(["first_person"], "依我看这样会更好。")["simplified_text"] == "这样会更好。"
    assert _text(["first_person"], "我想写一个解析函数。")["simplified_text"] == "写一个解析函数。"


def test_first_person_keeps_distinctive_wo():
    """保留承载区分信息的「我/我的」（我和张三 / 我的账号）。"""
    assert _text(["first_person"], "我和张三的日程冲突了。")["simplified_text"] == "我和张三的日程冲突了。"
    assert _text(["first_person"], "把我的账号和你的账号分开。")["simplified_text"] == "把我的账号和你的账号分开。"


def test_first_person_negated_preserved():
    """否定辖域内的自指标记保留（复用 _NEG_LOOKBEHIND）。"""
    assert _text(["first_person"], "别给我发邮件了。")["simplified_text"] == "别给我发邮件了。"
    assert _text(["first_person"], "不要帮我做这事。")["simplified_text"] == "不要帮我做这事。"


def test_first_person_want_verb_anchor():
    """「我想」仅锚定动词才删，避免误删「我想你/我想家」。"""
    assert _text(["first_person"], "我想你一切安好。")["simplified_text"] == "我想你一切安好。"
    assert _text(["first_person"], "我想回家了。")["simplified_text"] == "我想回家了。"  # 家非动词锚定集


def test_redundant_adverbs_keeps_discriminative():
    """深化：副词后接对比词（不同/相反/独立…）时保留（区分性用法）。"""
    assert _text(["redundant_adverbs"], "完全不同的方案才可行。")["simplified_text"] == "完全不同的方案才可行。"
    assert _text(["redundant_adverbs"], "绝对独立的模块更好维护。")["simplified_text"] == "绝对独立的模块更好维护。"
    # 非区分性用法仍删
    assert _text(["redundant_adverbs"], "非常稳定的服务。")["simplified_text"] == "稳定的服务。"


def test_meta_comment_strict_transition_only():
    """深化：需要注意的是/值得注意的是仅纯过渡（句首且后接，/。）才删。"""
    assert _text(["meta_comment"], "需要注意的是，任务很简单。")["simplified_text"] == "任务很简单。"
    # 句首但后接关键内容 → 保留
    assert _text(["meta_comment"], "需要注意的是必须验证输入。")["simplified_text"] == "需要注意的是必须验证输入。"
    # 句中 → 保留
    assert _text(["meta_comment"], "这里，需要注意的是性能。")["simplified_text"] == "这里，需要注意的是性能。"


def test_logical_connector_unordered_list_protected():
    """深化（P1-2）：无序列表行内序列词（首先/然后/最后）受保护不删。"""
    text = "- 首先安装依赖\n- 然后运行测试\n- 最后打包"
    out = _text(["logical_connector"], text)["simplified_text"]
    assert "首先" in out and "然后" in out and "最后" in out


def test_mode_difference_perceptible():
    """aggressive 预设规则 ⊃ balanced（多 first_person/hedging/...），同输入输出可辨。

    注：后端 PRESETS 两种模式均仅 5 基础类（零回归硬契约），模式差异由调用方
    （前端）以不同 explicit 规则集实现；此处用显式规则集复现该差异。
    """
    text = "你好，请给我写一个爬虫，要能爬豆瓣TOP250，并且把结果存成CSV。另外，我希望你能处理好反爬，这个爬虫最好能非常稳定地运行。谢谢！"
    balanced_rules = ["politeness", "role_prefix", "empty_items", "duplicate_lines",
                      "blank_lines", "meta_comment", "filler_particles",
                      "duplicate_clauses", "punctuation_compress", "punctuation_normalize"]
    aggressive_rules = balanced_rules + ["first_person", "hedging", "redundant_adverbs",
                                         "examples_trim", "logical_connector"]
    balanced = simplify_prompt(text, rules=balanced_rules)["simplified_text"]
    aggressive = simplify_prompt(text, rules=aggressive_rules)["simplified_text"]
    # aggressive 删第一人称受益标记（给我），balanced 保留
    assert "给我" in balanced and "给我" not in aggressive
    assert balanced != aggressive
    assert len(aggressive) < len(balanced)


def test_rules_none_zero_regression():
    """rules=None 仍 ≡ v2.5：PRESETS 仅 5 基础类，且不触发任何 v2.11 新类别。"""
    from skillforge.prompt_simplifier import PRESETS
    assert set(PRESETS["balanced"]) == {"politeness", "role_prefix", "empty_items", "duplicate_lines", "blank_lines"}
    assert set(PRESETS["aggressive"]) == {"politeness", "role_prefix", "empty_items", "duplicate_lines", "blank_lines"}
    text = "请给我写个爬虫，我希望你能处理好反爬。帮我看看报错。"
    none = simplify_prompt(text, rules=None)["simplified_text"]
    # 零回归核心信号：rules=None 仅走 PRESETS(5 基础类)，first_person 等新类别不触发，
    # 裸「给我」必须原样保留（它只被 first_person 删，而 first_person 不在 PRESETS）。
    assert "给我" in none
    # v2.5 基础礼貌类仍正常生效（rules=None 未退化）：「我希望」被基础礼貌表移除。
    assert "我希望" not in none
    # 「帮我」仅 explicit 扩展集才删，rules=None（v2.5 原表）保留。
    assert "帮我" in none


# ---------- v2.12 检测增强（courtesy_boilerplate + 现有规则词表召回扩展） ----------


def test_courtesy_boilerplate_removes_noise():
    """勾选后：招呼/道歉/感谢等纯礼貌噪声被移除；指令语气词（请/帮我）由其他规则处理，不在此删。"""
    out = _text(["courtesy_boilerplate"], "你好，请帮我写个爬虫，谢谢，辛苦了。")["simplified_text"]
    assert "你好" not in out and "谢谢" not in out and "辛苦了" not in out
    # 请/帮我 不在 courtesy 范畴，原样保留（由 politeness / first_person 处理）
    assert "请帮我写个爬虫" in out


def test_courtesy_boilerplate_unit_removal_before_politeness():
    """「感谢你/谢谢你」作为整体单元移除（courtesy 置 politeness 之前），不残留孤立「你」。"""
    out = _text(["courtesy_boilerplate", "redundant_adverbs"], "非常感谢你，运行稳定。")["simplified_text"]
    assert "你" not in out          # 感谢你 整体删除
    assert "感谢" not in out
    assert "非常" not in out        # 冗余副词随后删


def test_courtesy_boilerplate_explicit_only():
    """未显式勾选（rules=['blank_lines'] 兜底）时绝不触发，呼应零回归契约。"""
    out = _text(["blank_lines"], "你好，谢谢你的帮助。")["simplified_text"]
    assert "你好" in out and "谢谢" in out


def test_courtesy_boilerplate_keeps_apology_meaning():
    """道歉词整体移除（不好意思/打扰了），不影响相邻实义。"""
    out = _text(["courtesy_boilerplate"], "不好意思，这个接口报错了。")["simplified_text"]
    assert "不好意思" not in out
    assert "这个接口报错了" in out


def test_hedging_recall_expanded():
    """v2.12 召回扩展：未免/大抵 等弱语气词（后接非负面结果）现可检测移除。

    注：v2.13 起「搞不好会失败」因诚实不确定性护栏被保留，故此处不再断言 搞不好 删除。
    """
    out = _text(["hedging"], "这个方案未免太复杂，大抵可行。")["simplified_text"]
    assert "未免" not in out and "大抵" not in out


def test_hedging_keeps_honest_uncertainty():
    """v2.13 诚实不确定性护栏：认知不确定性 hedge 后接负面结果词时保留，防语义翻转。

    - 直接后接负面词（可能不可行）→ 保留；
    - 间隔连接小品词（会）：搞不好会失败 / 也许会有问题 → 保留；
    - 非负面后接（或许 + 不完全成立）→ 照常删除。
    """
    assert _text(["hedging"], "请评估方案，可能不可行。")["simplified_text"] == "请评估方案，可能不可行。"
    assert _text(["hedging"], "搞不好会失败，请重试。")["simplified_text"] == "搞不好会失败，请重试。"
    assert _text(["hedging"], "也许会有问题，需排查。")["simplified_text"] == "也许会有问题，需排查。"
    assert _text(["hedging"], "或许不完全成立，请修正。")["simplified_text"] == "不完全成立，请修正。"


def test_score_sentence_importance():
    """v2.13 句级重要性打分：含指令/数字者高，纯客套/闲聊者低。"""
    from skillforge.prompt_simplifier import _score_sentence_importance
    # 含指令提示词 + 数字 → 高
    assert _score_sentence_importance("请调用此接口并返回 JSON 结果。") >= 0.35
    assert _score_sentence_importance("实验在 4 张 A100 显卡上跑了 12 小时才收敛。") >= 0.35
    # 纯客套 / 闲聊 → 低
    assert _score_sentence_importance("感谢您的帮助。") < 0.35
    assert _score_sentence_importance("今天天气真好。") < 0.35
    # 空句 → 0
    assert _score_sentence_importance("") == 0.0


def test_redundant_adverbs_recall_expanded():
    """v2.12 召回扩展：格外/尤为 等冗余强调副词现可检测移除。"""
    out = _text(["redundant_adverbs"], "这个格外稳定，尤为重要的模块。")["simplified_text"]
    assert "格外" not in out and "尤为" not in out


def test_meta_comment_recall_expanded():
    """v2.12 召回扩展：说真的/坦白说 等元评论现可检测移除。"""
    out = _text(["meta_comment"], "说真的，坦白说这个项目很简单。")["simplified_text"]
    assert "说真的" not in out and "坦白说" not in out


def test_logical_connector_recall_expanded():
    """v2.12 召回扩展：在此基础上/从而 等连接词现可检测移除（条件标记不进集，安全）。"""
    out = _text(["logical_connector"], "在此基础上，我们需要启动，从而完成目标。")["simplified_text"]
    assert "在此基础上" not in out and "从而" not in out


def test_first_person_recall_expanded():
    """v2.12 召回扩展：我以为/代我/依我之见 等第一人称自指标记现可检测移除。"""
    out = _text(["first_person"], "我以为这样更好，代我处理，依我之见可行。")["simplified_text"]
    assert "我以为" not in out and "代我" not in out and "依我之见" not in out


def test_punctuation_normalize_fullwidth_space():
    """v2.12：全角空格（U+3000）紧邻 CJK 标点同样归一化。"""
    out = _text(["punctuation_normalize"], "你好　，　世界。")["simplified_text"]
    assert out == "你好，世界。"


# ---------- v2.9 新增类别（semantic_compress，本地语义压缩，explicit-only） ----------

class _FakeDenseBackend:
    """测试用稠密后端：以首 token 为「主题」，同主题余弦=1.0、异主题=0.0（正交）。

    使用确定性的「主题→唯一维度」one-hot 映射，避免依赖 hash()（受
    PYTHONHASHSEED 影响会产生碰撞，使异主题被误判为相同，导致相关用例
    在某些哈希种子下非确定性失败）。每个不同主题分配到唯一维度，保证
    同主题向量完全相等（余弦 1.0）、异主题向量正交（余弦 0.0）。
    """

    def __init__(self):
        self._topic_idx = {}
        self._next = 0
        self._dim = 64

    def vectorize(self, text):
        topic = (text.strip().split(" ", 1)[0] or "x")
        idx = self._topic_idx.get(topic)
        if idx is None:
            idx = self._next
            self._topic_idx[topic] = idx
            self._next += 1
        v = [0.0] * self._dim
        v[idx % self._dim] = 1.0
        return v


def test_semantic_threshold_clamp():
    """阈值越界/非法静默回落默认 0.90，区间内原值。"""
    assert _semantic_threshold_clamp("abc") == 0.90
    assert _semantic_threshold_clamp(None) == 0.90
    assert _semantic_threshold_clamp(0.5) == 0.90       # 低于下限
    assert _semantic_threshold_clamp(0.99) == 0.90      # 高于上限
    assert _semantic_threshold_clamp(0.85) == 0.85      # 区间内


def test_semantic_compress_near_dup_fold():
    """注入稠密后端：同主题近义句折叠后续，异主题保留。"""
    text = "T1 请帮我检查一下这段代码。T1 帮我看看这段程序有没有问题。T2 另一个完全不同的主题。"
    out, n = _rule_semantic_compress(text, False, True, threshold=0.90, backend=_FakeDenseBackend())
    assert n == 1
    assert "帮我看看这段程序" not in out
    assert "请帮我检查一下这段代码" in out
    assert "另一个完全不同" in out


def test_semantic_compress_distinct_kept():
    """异主题（相似度 0）默认阈值下不误删。"""
    text = "T1 主题A内容。T2 主题B内容。"
    out, n = _rule_semantic_compress(text, False, True, threshold=0.90, backend=_FakeDenseBackend())
    assert n == 0
    assert out == text


def test_semantic_compress_high_threshold_still_folds_identical():
    """阈值拉到上限 0.98，同主题（余弦 1.0）仍折叠。"""
    text = "T1 近义句一。T1 近义句二。"
    out, n = _rule_semantic_compress(text, False, True, threshold=0.98, backend=_FakeDenseBackend())
    assert n == 1


def test_semantic_compress_explicit_only_zero_regression():
    """rules=None 路径不含 semantic_compress，近义句不被折叠（零回归）。"""
    text = "T1 近义句一。T1 近义句二。"
    out = simplify_prompt(text, rules=None)
    assert out["simplified_text"] == text
    assert "semantic_compress" not in out.get("changes", [])


def test_semantic_compress_embedding_fallback(monkeypatch):
    """无稠密 embedding（local-tfidf / 端点不可达）→ 静默跳过，输出不变、无变更日志。"""
    from skillforge import prompt_simplifier
    monkeypatch.setattr(prompt_simplifier, "_get_semantic_backend", lambda: None)
    text = "T1 近义句一。T1 近义句二。"
    out = simplify_prompt(text, rules=["semantic_compress"])
    assert out["simplified_text"] == text
    assert not any("语义压缩" in c for c in out.get("changes", []))


def test_semantic_compress_combines_with_existing(monkeypatch):
    """与 politeness 等现有规则组合时顺序正确、确定性可复现。"""
    from skillforge import prompt_simplifier
    monkeypatch.setattr(prompt_simplifier, "_get_semantic_backend", lambda: _FakeDenseBackend())
    text = "T1 请帮我做A。T1 帮我做A的另一种说法。"
    out = simplify_prompt(text, rules=["politeness", "semantic_compress"])
    assert "请" not in out["simplified_text"]
    assert "帮我做A的另一种说法" not in out["simplified_text"]


def test_semantic_compress_prune_offtopic(monkeypatch):
    """prune=True：离题客套低信息句被剪枝，含指令句（请）保留。"""
    from skillforge import prompt_simplifier
    monkeypatch.setattr(prompt_simplifier, "_get_semantic_backend", lambda: _FakeDenseBackend())
    text = "T1 请执行此操作并生成报告。T1 重复描述同一指令。T2 闲聊寒暄客套话。"
    out, n = _rule_semantic_compress(
        text, False, True, threshold=0.90, prune=True, backend=_FakeDenseBackend(),
    )
    assert "闲聊寒暄客套话" not in out
    assert "请执行此操作" in out
    assert n >= 2  # 至少 1 处近义折叠 + 1 处剪枝


def test_semantic_compress_prune_keeps_substantive_offtopic(monkeypatch):
    """evo2-13 重要性门控：离题但含实质（数字/专名）的句被保留，防误删 useful substance。

    对齐 AGENTS.MD「Prefer useful substance over artificial brevity」：低信息客套才剪，
    含数字/专名的背景句即便离题也保留。
    """
    from skillforge import prompt_simplifier
    monkeypatch.setattr(prompt_simplifier, "_get_semantic_backend", lambda: _FakeDenseBackend())
    text = (
        "T1 请执行此操作并生成报告。T1 重复描述同一指令。"
        "T2 实验在 4 张 A100 显卡上跑了 12 小时才收敛，GPU 利用率 95%。"
    )
    out, n = _rule_semantic_compress(
        text, False, True, threshold=0.90, prune=True, backend=_FakeDenseBackend(),
    )
    # 离题但含实质（数字 + 专名）→ 保留
    assert "4 张 A100 显卡" in out
    # 近义折叠仍发生
    assert n >= 1

