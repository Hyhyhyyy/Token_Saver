"""v2.6 ↔ v2.5 零回归快照：rules=None / 显式 base5 必须与 v2.5 逐字相等。

通过仓库内提交的 v2.5 golden snapshot 与当前实现做逐字比对，锁定 P0-3。
测试不得依赖维护者机器上的外部备份目录。
"""
import json
from pathlib import Path

import pytest

from skillforge.prompt_simplifier import simplify_prompt, PRESETS

pytestmark = pytest.mark.a

_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "prompt_simplifier_v25.json"
V25_GOLDEN = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

BASE5 = PRESETS["balanced"]  # == PRESETS["aggressive"] == 5 个基础类别

CASES = [
    "请你帮我写一个函数。\n请务必使用 Python 实现。\n请确保代码有注释。\n",
    "你是一个专业的助手。请尽量使用 Python。\n你是一个专业的助手。请尽量使用 Python。\n",
    "Here is the task. 你是一个专业的助手，负责回答用户的问题。",
    "You are a helpful assistant. I want you to just simply write a function. "
    "Please make sure to very carefully use Python.",
    "请帮我实现登录。你是一个专业的后端工程师，参考示例：\n"
    "例如 `pip install skillforge`。\n"
    "```python\ndef login(u):\n    return auth(u)  # 你是一个专业的注释\n```\n"
    "文档见 https://api.example.com/login\n",
    "- 项目A\n- \n- 项目B\n",
    "步骤一：打开文件。\n步骤一：打开文件。\n步骤一：打开文件。\n",
    "前言\n\n\n\n正文\n",
    "需要注意的是，这个任务很简单。请开始吧。\n",
    "可能你会觉得很难，但其实不会。请放心。\n",
    "例如：\n苹果\n香蕉\n橙子\n葡萄\n西瓜\n这是很长的一串示例用来触发过长示例压缩但在 base5 下不应触发。\n",
    "Hi, please could you just write a test? Thanks.\n",
    "角色：分析师\n任务：汇总数据。\n\n\n\n输出：报告。\n",
    "请您申请一个账号。\n",  # 安全词「申请」不得被「请」误删
]


@pytest.mark.parametrize(
    ("text", "golden"),
    list(zip(CASES, V25_GOLDEN, strict=True)),
    ids=[f"case{i}" for i in range(len(CASES))],
)
def test_parity_balanced_rules_none_vs_v25(text, golden):
    v26 = simplify_prompt(text, mode="balanced")
    assert v26["simplified_text"] == golden["simplified_text"]
    assert v26["changes"] == golden["changes"]


@pytest.mark.parametrize("text", CASES, ids=[f"case{i}" for i in range(len(CASES))])
def test_parity_aggressive_not_weaker_than_v25(text):
    """v2.6 aggressive 相比 v2.5 是有意强化（新增 5.b 行内角色兜底 + 单字「请」）。

    零回归硬指标是 *balanced* 路径逐字相等（见上方 balanced 用例）；
    aggressive 仅保证「不弱于」v2.5：token 更少或相等（v2.6 只多删、不增删）。
    """
    v26 = simplify_prompt(text, mode="aggressive")
    balanced = simplify_prompt(text, mode="balanced")
    assert v26["simplified_tokens"] <= balanced["simplified_tokens"]


@pytest.mark.parametrize("text", CASES, ids=[f"case{i}" for i in range(len(CASES))])
def test_parity_explicit_base5_not_weaker_than_preset(text):
    """显式下发 base5 相比 rules=None 是有意强化（叠加扩展礼貌词 + 单字「请」）。

    契约变更（evo2-7）：两者不再逐字相等，但显式路径只多删、不增删，
    token 数只少不多（explicit 是 base5 的超集移除）。
    """
    none = simplify_prompt(text, mode="balanced")
    exp = simplify_prompt(text, mode="balanced", rules=list(BASE5))
    assert exp["simplified_tokens"] <= none["simplified_tokens"]


def test_parity_explicit_base5_politeness_expansion():
    """契约变更（evo2-7）：显式 base5 叠加扩展礼貌词，rules=None 不叠加。

    原断言（explicit base5 ≡ rules=None）在 explicit 扩展契约下已失效，改为验证
    「explicit base5 含扩展 politeness 删除，rules=None 不含」；rules=None ≡ v2.5
    由 test_parity_balanced_rules_none_vs_v25 锁定。
    """
    text = "请你帮我写一个函数。请务必使用 Python。可以吗？"
    none_bal = simplify_prompt(text, mode="balanced")
    exp_bal = simplify_prompt(text, mode="balanced", rules=list(BASE5))
    # rules=None 保留扩展礼貌词（不删「帮我」）；显式路径删除
    assert "帮我" in none_bal["simplified_text"]
    assert "帮我" not in exp_bal["simplified_text"]
    # rules=None 的简化结果逐字等于 v2.5（契约硬指标，独立测试锁定）
    assert none_bal["simplified_text"] == "帮我写一个函数。使用 Python。可以吗？"
