"""P0-1 冲突规则沉淀去重（AUTO_EVOLVE_LOOP 下不无限膨胀）。

- 同一高相似冲突对多次 run_evolve 只沉淀 1 条规则、记 1 条 conflict_rule_deposit 账本。
- 不同高相似冲突对仍各自沉淀 1 条规则。
"""
import pytest

from skillforge import evolve, custom_rules, simbank

pytestmark = pytest.mark.a


def test_duplicate_pair_not_redeposited(skillforge_env):
    # 两个描述高度相同的技能 → 高相似冲突对（相似度 1.0）
    same_desc = "请生成营销文案及广告标语"
    skillforge_env.make_skill("dup-a", same_desc)
    skillforge_env.make_skill("dup-b", same_desc)

    r1 = evolve.run_evolve(trigger="t")
    assert len(r1["deposited_rules"]) == 1

    # 第二次运行（等价于 AUTO_EVOLVE_LOOP 再跑一轮）：相同冲突对不应再沉淀
    evolve.run_evolve(trigger="t")

    rules = custom_rules.load_custom_rules()
    assert len(rules) == 1, f"custom_rules 应仅 1 条，实际 {len(rules)}"

    ledger = simbank.get_ledger(action_type="conflict_rule_deposit", limit=50)
    assert ledger["count"] == 1, f"conflict_rule_deposit 应仅 1 条，实际 {ledger['count']}"


def test_new_pair_still_deposits(skillforge_env):
    # 描述 X 与 Y 字符集不相交 → 彼此不冲突；各自内部相同 → 各自成一对
    desc_x = "请生成营销文案及广告标语"
    desc_y = "清洗数据缺失项和异常检测"
    skillforge_env.make_skill("dup-a", desc_x)
    skillforge_env.make_skill("dup-b", desc_x)
    r1 = evolve.run_evolve(trigger="t")
    assert len(r1["deposited_rules"]) == 1

    # 新增一对全新高相似技能（不同于 X）
    skillforge_env.make_skill("dup-c", desc_y)
    skillforge_env.make_skill("dup-d", desc_y)
    r2 = evolve.run_evolve(trigger="t")
    assert len(r2["deposited_rules"]) == 1, "新冲突对应再沉淀 1 条"

    rules = custom_rules.load_custom_rules()
    assert len(rules) == 2, f"应沉淀 2 条不同冲突规则，实际 {len(rules)}"

    ledger = simbank.get_ledger(action_type="conflict_rule_deposit", limit=50)
    assert ledger["count"] == 2, f"conflict_rule_deposit 应 2 条，实际 {ledger['count']}"


def test_deposit_custom_rule_return_shape():
    # 直接验证 deposit_custom_rule 的去重返回结构
    from skillforge import config

    rules_path = config.CUSTOM_RULES_PATH
    rules_path.write_text("[]", encoding="utf-8")

    first = custom_rules.deposit_custom_rule(["alpha", "beta"], "建议差异化")
    assert first.get("deposited") is True
    assert first["id"]

    # 同样的 keyword_cluster（顺序不同）应被判重
    dup = custom_rules.deposit_custom_rule(["beta", "alpha"], "建议差异化")
    assert dup.get("deposited") is False
    assert dup.get("reason") == "duplicate"
    assert dup["id"] == first["id"]

    # 强制 dedupe=False 仍追加（向后兼容）
    forced = custom_rules.deposit_custom_rule(["beta", "alpha"], "建议差异化", dedupe=False)
    assert forced.get("deposited") is True
