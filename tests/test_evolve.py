"""编排 + B-3 no-op 判定 + 冲突自动沉淀。"""
from skillforge import evolve


def test_run_evolve_seeds_and_returns(skillforge_env):
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    r = evolve.run_evolve(trigger="test")
    assert r["gold"]["seeded"] == 2
    assert "ledger_new" in r
    assert r["no_op"] is False
    assert "gold_coverage" in r
    assert 0 <= r["gold_coverage"] <= 100


def test_no_op_after_full_coverage(skillforge_env):
    # 两个描述差异大的技能 → 无冲突命中、无匹配 gold 回归、首轮播种后次轮全覆盖
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    r1 = evolve.run_evolve(trigger="test")
    assert r1["gold"]["seeded"] == 2

    r2 = evolve.run_evolve(trigger="test")
    # B-3：gold 已全覆盖且本轮无新增回归/冲突 → no-op，不写 ledger/metrics
    assert r2["no_op"] is True
    assert r2["ledger_new"] == []


def test_conflict_auto_deposit(skillforge_env):
    # 两个描述高度相似（相同）→ embedding 余弦 ≥ 0.85 → 自动沉淀冲突规则
    same_desc = "这是一个用于生成营销文案的技能，擅长写 slogan 与广告语"
    skillforge_env.make_skill("dup-a", same_desc)
    skillforge_env.make_skill("dup-b", same_desc)
    r = evolve.run_evolve(trigger="test")
    assert len(r["deposited_rules"]) >= 1

    from skillforge import simbank
    ledger = simbank.get_ledger(action_type="conflict_rule_deposit", limit=50)
    assert ledger["count"] >= 1
    # 自动循环条目 trigger 经下传（此处为手动 test）
    assert all(e["trigger"] == "test" for e in ledger["entries"])
