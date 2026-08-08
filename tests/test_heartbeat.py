"""A-2 / A-3：heartbeat 连续时间序列（no-op 轮次也写 evolution_metrics）+ 低水位再播种。

验证：无实际业务动作的 no-op 轮次仍写一行趋势点（趋势图连续）；低水位分支触发再播种。
"""
import pytest

from skillforge import config, evolve, simbank

pytestmark = pytest.mark.a


def _write_skill(skills_dir, name, desc):
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n", encoding="utf-8"
    )


def test_heartbeat_writes_metric_on_noop(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程")
    _write_skill(skillforge_env.skills_dir, "beta", "生成Python数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    pts_before = len(simbank.get_evolution_metrics())

    # 无变化再跑：应为 no-op 业务（不写 ledger 业务条目），但 heartbeat 仍写一行 metrics
    r = evolve.run_evolve(trigger="t")
    assert r["no_op"] is True
    pts_after = len(simbank.get_evolution_metrics())
    assert pts_after == pts_before + 1


def test_heartbeat_continuous_across_runs(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程")
    evolve.run_evolve(trigger="t")
    # 反复 no-op 运行，趋势点应持续累积（不只在收敛点停留）
    for _ in range(3):
        evolve.run_evolve(trigger="t")
    pts = simbank.get_evolution_metrics()
    assert len(pts) >= 4
    # 按 ts 升序
    assert all(pts[i]["ts"] <= pts[i + 1]["ts"] for i in range(len(pts) - 1))


def test_low_watermark_triggers_reseed(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "alpha", "描述A")
    _write_skill(skillforge_env.skills_dir, "beta", "描述B")
    calls = {"n": 0}
    orig = evolve.bootstrap_gold

    def spy(force=False, threshold=None, trigger="auto_bootstrap"):
        calls["n"] += 1
        return orig(force=force, threshold=threshold, trigger=trigger)

    evolve.bootstrap_gold = spy
    orig_cov = evolve._compute_gold_coverage
    # 强制覆盖度低于低水位阈值，触发再播种分支
    evolve._compute_gold_coverage = lambda: 50.0
    try:
        r = evolve.run_evolve(trigger="t")
    finally:
        evolve.bootstrap_gold = orig
        evolve._compute_gold_coverage = orig_cov
    # 低水位分支：bootstrap_gold 至少被调用 2 次（常规 + 低水位），且不崩溃
    assert calls["n"] >= 2
    assert r["gold_coverage"] == 50.0
    # 低水位后 coverage 字段正确落在 [0,100]
    assert 0 <= r["gold_coverage"] <= 100
