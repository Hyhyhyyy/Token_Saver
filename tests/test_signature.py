"""A-1：技能内容签名计算/比对/changeset；外部变化触发 skill_signature_change 账本；幂等。

验证：首次运行仅建立基线（不误报 skill_signature_change）；新增技能触发再进化并写账本；
无变化时重复 run_evolve 不重复入库 gold（bootstrap_gold 幂等）。
"""
import pytest

from skillforge import evolve, simbank, gold, skill_signature

pytestmark = pytest.mark.a


def _write_skill(skills_dir, name, desc):
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n", encoding="utf-8"
    )


def test_compute_and_compare(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "skill-x", "处理用户订单退款流程")
    sigs = skill_signature.compute_signatures(skillforge_env.skills_dir)
    assert "skill-x" in sigs and len(sigs["skill-x"]) == 64  # sha256 hex
    # 尚无保存的基线
    assert skill_signature.load_saved_signatures() == {}
    cs = skill_signature.compare_signatures(sigs, {})
    assert cs["added"] == ["skill-x"]
    assert cs["removed"] == [] and cs["changed"] == []


def test_change_detected_after_content_edit(skillforge_env):
    import shutil

    _write_skill(skillforge_env.skills_dir, "skill-x", "描述版本一")
    skill_signature.save_signatures(skill_signature.compute_signatures())
    # 修改内容 → 命中 changed
    _write_skill(skillforge_env.skills_dir, "skill-x", "描述版本二，内容已变更")
    cs, ext = skill_signature.detect_external_change()
    assert ext is True
    assert cs["changed"] == ["skill-x"]
    # 删除技能 → 命中 removed
    shutil.rmtree(skillforge_env.skills_dir / "skill-x")
    cs2, ext2 = skill_signature.detect_external_change()
    assert ext2 is True
    assert cs2["removed"] == ["skill-x"]


def test_external_change_triggers_ledger(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "skill-x", "处理用户订单退款流程")
    r1 = evolve.run_evolve(trigger="test")
    # 首次运行建立基线，不应有 skill_signature_change（避免误报初始播种）
    ledger1 = simbank.get_ledger(action_type="skill_signature_change", limit=10)
    assert ledger1["count"] == 0
    assert r1["no_op"] is False

    # 新增技能 → 下一轮触发 skill_signature_change
    _write_skill(skillforge_env.skills_dir, "skill-y", "生成数据可视化图表脚本")
    r2 = evolve.run_evolve(trigger="test")
    ledger2 = simbank.get_ledger(action_type="skill_signature_change", limit=10)
    assert ledger2["count"] == 1
    assert r2["no_op"] is False
    # 账本条目带变化清单与时间窗可查
    assert "skill-y" in ledger2["entries"][0]["after_val"]


def test_idempotent_repeat_run(skillforge_env):
    _write_skill(skillforge_env.skills_dir, "skill-x", "处理用户订单退款流程")
    _write_skill(skillforge_env.skills_dir, "skill-y", "生成数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    g0 = len(gold.get_gold())
    # 无变化再跑：gold 不重复入库
    evolve.run_evolve(trigger="t")
    g1 = len(gold.get_gold())
    assert g0 == g1
