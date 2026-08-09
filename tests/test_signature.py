"""A-1：技能内容签名计算/比对/changeset；外部变化触发 skill_signature_change 账本；幂等。

验证：首次运行仅建立基线（不误报 skill_signature_change）；新增技能触发再进化并写账本；
无变化时重复 run_evolve 不重复入库 gold（bootstrap_gold 幂等）。
R-1：改非 SKILL.md 文件（scripts/ 等）亦触发 external_change；schema 不符静默重建。
"""
import json

import pytest

from skillforge import evolve, simbank, gold, skill_signature, config

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


def _write_skill_with_script(skills_dir, name, desc, script_body):
    """写一个含 SKILL.md 与 scripts/ 子目录文件的技能（R-1 关键目录用例）。"""
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n", encoding="utf-8"
    )
    scripts_dir = d / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "helper.py").write_text(script_body, encoding="utf-8")
    return d


def test_external_change_on_non_skillmd_edit(skillforge_env):
    """R-1：改技能目录下非 SKILL.md 文件（scripts/ 等）亦触发 external_change=True。

    v2.3 仅扫 SKILL.md 内容，改 scripts/ 不会触发；v2.4 复合指纹（清单 + 全文件 mtime
    + 关键目录内容哈希）覆盖 scripts/，故改 scripts/helper.py 也应命中 changed。
    """
    _write_skill_with_script(
        skillforge_env.skills_dir, "skill-x", "基线技能",
        "def helper():\n    return 1\n",
    )
    # 建立基线（带 _schema）
    skill_signature.save_signatures(skill_signature.compute_signatures())

    # 仅修改 scripts/ 下文件（非 SKILL.md）→ 命中 changed
    scripts_dir = skillforge_env.skills_dir / "skill-x" / "scripts"
    (scripts_dir / "helper.py").write_text(
        "def helper():\n    return 2  # 已修订\n", encoding="utf-8"
    )
    cs, ext = skill_signature.detect_external_change()
    assert ext is True
    assert cs["changed"] == ["skill-x"]
    assert cs["added"] == []
    assert cs["removed"] == []


def test_schema_mismatch_silent_rebuild(skillforge_env):
    """R-1：schema 不符时 load 返回 {} 且 detect_external_change 不记账本（静默重建）。

    模拟从 v2.3 升级：skills_signature.json 仅含 {技能名: hex}（无 _schema 元字段）。
    load_saved_signatures 应返回 {}（视为无基线）；据此 external_change=False，
    run_evolve 不写 skill_signature_change 账本——避免升级首跑因旧 SKILL.md-only 指纹
    格式不同而误报；升级后基线被静默重建（带 _schema）。
    """
    path = skillforge_env.data_dir / "skills_signature.json"
    # 旧 v2.3 格式：纯 {技能名: hex}，无 _schema 元字段
    path.write_text(
        json.dumps({"skill-x": "a" * 64}, ensure_ascii=False), encoding="utf-8"
    )
    # 直接读取即应返回 {}（schema 不符 → 静默视为无基线）
    assert skill_signature.load_saved_signatures(path) == {}

    # 预置技能（用于真实计算当前签名）
    _write_skill(skillforge_env.skills_dir, "skill-x", "基线技能")

    # 用旧 schema 基线跑 evolve：external_change=False，不应写 skill_signature_change 账本
    evolve.run_evolve(trigger="test")
    ledger = simbank.get_ledger(action_type="skill_signature_change", limit=10)
    assert ledger["count"] == 0
    # 升级后基线被静默重建（带 _schema 元字段，load 不再返回 {}）
    assert skill_signature.load_saved_signatures(path) != {}
