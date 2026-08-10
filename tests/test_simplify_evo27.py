"""evo2-7 专项回归：逻辑连接词 / 句末语气词 / 显式礼貌词强化 / 弱语气词强化。

锁定新增两类规则（logical_connector / filler_particles）与 explicit 扩展契约：
- rules=None 路径不受任何影响（≡ v2.5，由 test_simplify_parity 锁定）；
- 仅当用户显式勾选 / 下发 rules（explicit=True）时新类别生效。
"""
import pytest

from skillforge.prompt_simplifier import simplify_prompt, PRESETS

pytestmark = pytest.mark.a

BASE5 = PRESETS["balanced"]


def test_logical_connector_keeps_instructions():
    """逻辑连接词移除，但指令性动词 / 参数 / 关键名词全部保留。"""
    text = (
        "首先，读取 config.yaml 中的 token 配置。"
        "然后启动 server，并因此记录日志。"
        "最后验证结果是否正确。"
    )
    # 非列表游离上下文：序列词与因果词均移除
    on = simplify_prompt(text, mode="balanced", rules=["logical_connector"])
    out = on["simplified_text"]
    assert "首先" not in out
    assert "然后" not in out
    assert "因此" not in out
    assert "最后" not in out
    # 指令与参数保留
    assert "读取" in out and "config.yaml" in out
    assert "token" in out and "server" in out and "日志" in out
    assert "验证" in out and "结果" in out


def test_logical_connector_protects_conditional_and_ordered_list():
    """条件标记（如果/则/否则）不删；有序列表行内序列词受局部哨兵保护不删。"""
    cond = "如果文件存在，则读取它；否则创建新文件并写入默认配置。"
    rc = simplify_prompt(cond, mode="balanced", rules=["logical_connector"])
    assert "如果" in rc["simplified_text"]
    assert "则" in rc["simplified_text"]
    assert "否则" in rc["simplified_text"]
    assert "写入" in rc["simplified_text"]

    # 多种有序列表标记：1. / (1) / 第一、 / 步骤一
    lst = (
        "1. 首先打开文件。\n"
        "(2) 然后解析内容。\n"
        "第三、接着校验格式。\n"
        "步骤四：最后保存结果。"
    )
    rl = simplify_prompt(lst, mode="balanced", rules=["logical_connector"])
    out = rl["simplified_text"]
    assert "首先" in out and "然后" in out and "接着" in out and "最后" in out
    assert "1." in out and "(2)" in out and "第三、" in out and "步骤四" in out
    # 局部哨兵已被还原，不应残留 \\x01
    assert "\x01" not in out


def test_filler_particles_safe():
    """句末语气助词移除；「吗」保留（疑问句）；句中谨慎不删；否定前瞻保护。"""
    text = "你帮我看看这个啊。它可以运行吧？请确认嘛。这是真的吗？嗯，好的呢需要通过测试。"
    on = simplify_prompt(text, mode="balanced", rules=["filler_particles"])
    out = on["simplified_text"]
    # 句末移除
    assert "啊" not in out
    assert "吧" not in out
    assert "嘛" not in out
    # 疑问句「吗」保留
    assert "吗" in out
    # 句中「呢」不删
    assert "呢" in out
    # 否定前瞻：构造「不啊」紧贴也不误删
    neg = simplify_prompt("这并不啊。", mode="balanced", rules=["filler_particles"])
    assert "不啊" in neg["simplified_text"]


def test_politeness_explicit_only():
    """扩展礼貌词仅 explicit=True（下发 rules）时叠加；rules=None 不删。"""
    text = "请你帮我写代码，可以吗？"
    none = simplify_prompt(text, mode="balanced")  # rules=None → explicit=False
    exp = simplify_prompt(text, mode="balanced", rules=list(BASE5))  # explicit=True
    assert "帮我" in none["simplified_text"]
    assert "帮我" not in exp["simplified_text"]
    # 单字「请」在显式 balanced 删除；rules=None 保留
    assert "请开始" in simplify_prompt("请开始写。", mode="balanced")["simplified_text"]
    assert "请开始" not in simplify_prompt("请开始写。", mode="balanced", rules=list(BASE5))["simplified_text"]


def test_hedging_strengthened():
    """hedging 强化：多字安全词移除；单字「应」刻意排除，不误伤应用/响应。"""
    text = "你应该估计一下，难免出错，大体上可行。应用此配置响应请求。"
    on = simplify_prompt(text, mode="balanced", rules=["hedging"])
    out = on["simplified_text"]
    assert "应该" not in out
    assert "估计" not in out
    assert "难免" not in out
    assert "大体上" not in out
    assert "应用" in out
    assert "响应" in out
