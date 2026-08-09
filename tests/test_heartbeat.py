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


def test_heartbeat_writes_metric_on_noop(skillforge_env, monkeypatch):
    # A-5 节流：本次用例意图是验证「no-op 轮次仍写一行趋势点（趋势连续）」。
    # 把节流间隔置 0，使「间隔已超」恒成立 → 每个 no-op 仍写一行 metrics，
    # 兼容 v2.4 的 A-5 新语义（源码行为正确，旧断言冲突仅因节流，故属测试侧修复）。
    monkeypatch.setattr(config, "HEARTBEAT_MIN_INTERVAL_SEC", 0.0)
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程")
    _write_skill(skillforge_env.skills_dir, "beta", "生成Python数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    pts_before = len(simbank.get_evolution_metrics())

    # 无变化再跑：应为 no-op 业务（不写 ledger 业务条目），但 heartbeat 仍写一行 metrics
    r = evolve.run_evolve(trigger="t")
    assert r["no_op"] is True
    pts_after = len(simbank.get_evolution_metrics())
    assert pts_after == pts_before + 1


def test_heartbeat_continuous_across_runs(skillforge_env, monkeypatch):
    # 同 test_heartbeat_writes_metric_on_noop：间隔置 0 以验证「连续时间序列」意图不被节流打断
    monkeypatch.setattr(config, "HEARTBEAT_MIN_INTERVAL_SEC", 0.0)
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程")
    evolve.run_evolve(trigger="t")
    # 反复 no-op 运行，趋势点应持续累积（不只在收敛点停留）
    for _ in range(3):
        evolve.run_evolve(trigger="t")
    pts = simbank.get_evolution_metrics()
    assert len(pts) >= 4
    # 按 ts 升序
    assert all(pts[i]["ts"] <= pts[i + 1]["ts"] for i in range(len(pts) - 1))


def test_heartbeat_throttled_on_identical_noop(skillforge_env):
    """A-5 节流验证（v2.4 新行为）：默认 HEARTBEAT_MIN_INTERVAL_SEC=60。

    - 首个 no-op 之后，连续且指标值相同的 no-op 在默认间隔内被节流（不新增 metrics 行）；
    - 改某个技能 SKILL.md（外部变化）→ 恢复写行（值变/有业务动作必写，趋势不中断）。
    该用例直接证明 A-5 节流确实生效，且「值变必写」保证连续。
    """
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程")
    evolve.run_evolve(trigger="t")  # 首个运行：播种 gold，非 no-op，写 1 行
    before = len(simbank.get_evolution_metrics())
    assert before >= 1

    # 连续相同 no-op（默认 60s 间隔内）→ 被节流，点数不变
    for _ in range(3):
        r = evolve.run_evolve(trigger="t")
        assert r["no_op"] is True
        assert r.get("throttled") is True
    assert len(simbank.get_evolution_metrics()) == before

    # 改 SKILL.md（外部变化）→ 恢复写行，点数 +1（值变/有业务动作必写）
    _write_skill(skillforge_env.skills_dir, "alpha", "处理用户订单退款与售后流程（已修订）")
    r2 = evolve.run_evolve(trigger="t")
    assert r2["no_op"] is False
    assert len(simbank.get_evolution_metrics()) == before + 1


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
