"""SkillForge v2.3 灵魂断点 · 独立真实验证（QA · 不依赖工程师的测试用例）。

每个验证小节使用独立临时 DATA_DIR/USER_SKILLS_DIR 并重新导入 skillforge，
彻底隔离（等价于 pytest fixture 的 function 级隔离），不触碰真实 ~/.workbuddy/skills 与远程 API。
仅用 Python 标准库。逐项真实验证 A-1/A-2/A-3/C-1/C-2/D-1/D-2，并给出 PASS/FAIL。

运行：
  <venv>/python.exe qa_soul_verify.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from types import SimpleNamespace


def setup_fresh(env_extra: dict | None = None) -> SimpleNamespace:
    """创建全新临时环境并重新导入 skillforge（隔离，等价于独立测试进程）。"""
    TMP = Path(tempfile.mkdtemp(prefix="skillforge_qa_"))
    DATA_DIR = TMP / "data"
    SKILLS = TMP / "skills"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS.mkdir(parents=True, exist_ok=True)

    os.environ["DATA_DIR"] = str(DATA_DIR)
    os.environ["USER_SKILLS_DIR"] = str(SKILLS)
    os.environ["SKILLS_DIRS"] = str(SKILLS)
    os.environ["AUTO_EVOLVE_LOOP"] = "false"
    os.environ["AUTO_EVOLVE_ON_START"] = "false"
    os.environ["GOLD_COVERAGE_LOW_WATERMARK"] = "80"
    if env_extra:
        os.environ.update(env_extra)

    (DATA_DIR / "vectorizer.json").write_text(
        json.dumps({"backend": "local-tfidf"}, ensure_ascii=False), encoding="utf-8"
    )

    for _n in list(sys.modules):
        if _n == "skillforge" or _n.startswith("skillforge."):
            del sys.modules[_n]

    import skillforge  # noqa: E402
    from skillforge import (  # noqa: E402
        config,
        evolve,
        simbank,
        gold,
        skill_signature,
        auto_loop,
        scorer,
        filelock,
    )

    ns = SimpleNamespace()
    ns.TMP = TMP
    ns.DATA_DIR = DATA_DIR
    ns.SKILLS = SKILLS
    ns.skillforge = skillforge
    ns.config = config
    ns.evolve = evolve
    ns.simbank = simbank
    ns.gold = gold
    ns.skill_signature = skill_signature
    ns.auto_loop = auto_loop
    ns.scorer = scorer
    ns.filelock = filelock
    return ns


_RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _RESULTS.append((cond, name, detail))
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


def write_skill(sk: SimpleNamespace, name: str, desc: str, body: str = "示例正文内容") -> None:
    d = sk.SKILLS / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n", encoding="utf-8"
    )


# =========================================================================== #
# A-2 heartbeat 连续时间序列（no-op 轮次也写 evolution_metrics）
# =========================================================================== #
def verify_a2_heartbeat():
    sk = setup_fresh()
    write_skill(sk, "alpha", "处理用户订单退款与售后流程")
    write_skill(sk, "beta", "生成Python数据可视化图表脚本")
    N = 5
    for _ in range(N):
        sk.evolve.run_evolve(trigger="qa_heartbeat")
    pts = sk.simbank.get_evolution_metrics()
    check("A-2 趋势点行数 == 调用次数", len(pts) == N, f"rows={len(pts)} calls={N}")
    check("A-2 至少有 2 个趋势点", len(pts) >= 2, f"points={len(pts)}")

    before = len(sk.simbank.get_evolution_metrics())
    r = sk.evolve.run_evolve(trigger="qa_heartbeat")
    after = len(sk.simbank.get_evolution_metrics())
    check("A-2 no-op 轮次也写 metrics", r["no_op"] is True and after == before + 1,
          f"no_op={r['no_op']} delta={after - before}")


# =========================================================================== #
# A-1 进化压力源（新增技能触发再进化 + 写账本 + 进 gold）—— 独立干净环境
# =========================================================================== #
def verify_a1_pressure():
    sk = setup_fresh()
    # 首轮建立基线，不应误报 skill_signature_change
    write_skill(sk, "p1", "处理用户订单退款流程")
    sk.evolve.run_evolve(trigger="qa_pressure")
    ledger1 = sk.simbank.get_ledger(action_type="skill_signature_change", limit=10)
    check("A-1 首次运行仅建基线(无 skill_signature_change)", ledger1["count"] == 0,
          f"count={ledger1['count']}")

    # 新增技能 → 下一轮触发 skill_signature_change
    write_skill(sk, "p2", "生成数据可视化图表脚本")
    sk.evolve.run_evolve(trigger="qa_pressure")
    ledger2 = sk.simbank.get_ledger(action_type="skill_signature_change", limit=10)
    check("A-1 新增技能写 skill_signature_change 账本", ledger2["count"] == 1,
          f"count={ledger2['count']}")
    check("A-1 账本条目含新增技能名",
          ledger2["count"] > 0 and "p2" in ledger2["entries"][0]["after_val"])
    sigs = sk.skill_signature.load_saved_signatures()
    check("A-1 skills_signature.json 含新增技能签名", "p2" in sigs,
          f"keys={list(sigs.keys())}")
    gold_ids = {g["skill_id"] for g in sk.gold.get_gold()}
    check("A-1 新增技能进入 gold", "p2" in gold_ids, f"gold_count={len(gold_ids)}")


# =========================================================================== #
# A-3 低水位再播种（coverage<80 触发再播种 + 非 no-op 写 metrics）
# =========================================================================== #
def verify_a3_lowwatermark():
    sk = setup_fresh()
    write_skill(sk, "lw1", "低水位场景技能一")
    write_skill(sk, "lw2", "低水位场景技能二")

    orig_cov = sk.evolve._compute_gold_coverage
    orig_bg = sk.evolve.bootstrap_gold
    bg_calls = {"n": 0}

    def spy(force=False, threshold=None, trigger="auto_bootstrap"):
        bg_calls["n"] += 1
        return orig_bg(force=force, threshold=threshold, trigger=trigger)

    sk.evolve.bootstrap_gold = spy
    sk.evolve._compute_gold_coverage = lambda: 50.0  # 强制覆盖率 < 低水位
    try:
        m_before = len(sk.simbank.get_evolution_metrics())
        r = sk.evolve.run_evolve(trigger="qa_lowwater")
        m_after = len(sk.simbank.get_evolution_metrics())
    finally:
        sk.evolve.bootstrap_gold = orig_bg
        sk.evolve._compute_gold_coverage = orig_cov

    check("A-3 低水位触发再播种(bootstrap>=2次)", bg_calls["n"] >= 2,
          f"bootstrap_calls={bg_calls['n']}")
    check("A-3 返回覆盖率==被压低值(50)", r["gold_coverage"] == 50.0,
          f"coverage={r['gold_coverage']}")
    check("A-3 本轮非 no-op(写了 metrics)",
          m_after == m_before + 1 and r["no_op"] is False,
          f"delta_metrics={m_after - m_before} no_op={r['no_op']}")

    # 真实流补充：watermark 设极高(999)→常规运行也触发低水位分支(证明阈值判断真实生效)
    sk2 = setup_fresh({"GOLD_COVERAGE_LOW_WATERMARK": "999"})
    write_skill(sk2, "lw3", "低水位场景技能三")
    bg2 = {"n": 0}
    o_bg = sk2.evolve.bootstrap_gold

    def spy2(force=False, threshold=None, trigger="auto_bootstrap"):
        bg2["n"] += 1
        return o_bg(force=force, threshold=threshold, trigger=trigger)

    sk2.evolve.bootstrap_gold = spy2
    try:
        r2 = sk2.evolve.run_evolve(trigger="qa_lowwater")
    finally:
        sk2.evolve.bootstrap_gold = o_bg
    check("A-3 高 watermark 真实触发再播种分支", bg2["n"] >= 2,
          f"bootstrap_calls={bg2['n']} coverage={r2['gold_coverage']}")


# =========================================================================== #
# C-1 auto_loop.start() 在运行 loop 内不抛 DeprecationWarning
# =========================================================================== #
def verify_c1_no_deprecation():
    sk = setup_fresh()

    async def go():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sk.auto_loop.start()
            sk.auto_loop.stop()
            return [w for w in caught if issubclass(w.category, DeprecationWarning)]

    depr = asyncio.run(go())
    check("C-1 start() 不抛 DeprecationWarning", not depr,
          f"deprecations={[str(w.message) for w in depr]}")


# =========================================================================== #
# C-2 跨进程文件锁占用 → run_once/run_protected 安全跳过；enabled=False 不阻塞
# =========================================================================== #
def verify_c2_filelock_skip():
    sk = setup_fresh()
    sk.config.FILELOCK_TIMEOUT_SEC = 0.3
    occupier = sk.filelock.FileLock(sk.config.LOCK_PATH, timeout=2.0)
    occupier.__enter__()
    try:
        async def go():
            return await sk.auto_loop.run_once("auto_loop")

        res = asyncio.run(go())
    finally:
        occupier.__exit__(None, None, None)

    check("C-2 锁占用时 run_once 安全跳过(skipped)",
          res.get("skipped") is True, f"res={res}")
    check("C-2 锁占用时 run_once 不崩溃且有占位字段",
          isinstance(res, dict) and "ledger_new" in res)

    occ2 = sk.filelock.FileLock(sk.config.LOCK_PATH, timeout=2.0)
    occ2.__enter__()
    try:
        async def go2():
            return await sk.auto_loop.run_protected(
                lambda: sk.evolve.run_evolve(trigger="qa"))

        res2 = asyncio.run(go2())
    finally:
        occ2.__exit__(None, None, None)
    check("C-2 锁占用时 run_protected 安全跳过(skipped)",
          res2.get("skipped") is True, f"res={res2}")

    async def go3():
        fl = sk.filelock.FileLock(sk.config.LOCK_PATH, timeout=1.0, enabled=False)
        with fl:
            return fl.acquired

    check("C-2 enabled=False 不阻塞(acquired=True)", asyncio.run(go3()) is True)


# =========================================================================== #
# D-1/D-2 ollama 探测/来源：不可用回退 local-tfidf；backend_source 正确
# =========================================================================== #
def verify_d_ollama():
    sk = setup_fresh()
    sk.config.VECTORIZER_PATH.unlink(missing_ok=True)
    sk.scorer.set_ollama_available(False)
    cfg = sk.scorer.ensure_default_vectorizer()
    check("D-1 ollama 不可用回退 local-tfidf", cfg["backend"] == "local-tfidf",
          f"backend={cfg.get('backend')}")
    check("D-1 回退写入 vectorizer.json", sk.config.VECTORIZER_PATH.exists())

    src = sk.scorer.resolve_backend_source()
    check("D-2 resolve_backend_source.backend_source 正确",
          src["backend_source"] == "local-tfidf", f"src={src}")
    check("D-2 resolve_backend_source 含 ollama_available 字段",
          "ollama_available" in src and src["ollama_available"] is False)

    sk.config.VECTORIZER_PATH.unlink(missing_ok=True)
    sk.scorer.set_ollama_available(True)
    cfg2 = sk.scorer.ensure_default_vectorizer()
    check("D-1 ollama 可用复制预设(local-st)",
          cfg2.get("provider") == "local-st", f"cfg={cfg2}")
    check("D-1 落地内容为 local-st 预设",
          "local-st" in sk.config.VECTORIZER_PATH.read_text(encoding="utf-8"))

    before = sk.config.VECTORIZER_PATH.read_text(encoding="utf-8")
    sk.scorer.ensure_default_vectorizer()
    after = sk.config.VECTORIZER_PATH.read_text(encoding="utf-8")
    check("D-1 已存在配置不被覆盖", before == after)


# =========================================================================== #
# Edge cases：签名文件损坏 / preset 缺失回退 / 锁获取超时
# =========================================================================== #
def verify_edge_cases():
    # E1：签名文件损坏 → load_saved_signatures 容错返回 {}，且 detect_external_change 不崩溃
    sk = setup_fresh()
    sk.config.SKILLS_SIGNATURE_PATH.write_text("{ this is not valid json ", encoding="utf-8")
    sigs = sk.skill_signature.load_saved_signatures()
    check("EDGE 损坏签名文件 → load_saved_signatures 返回 {}", sigs == {}, f"sigs={sigs}")
    try:
        cs, ext = sk.skill_signature.detect_external_change()
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        cs, ext = None, None
    check("EDGE 损坏签名文件 → detect_external_change 不崩溃", ok,
          f"cs={cs} ext={ext}")

    # E2：vectorizer.local-st.json preset 缺失 → ensure_default_vectorizer 回退 local-tfidf
    sk2 = setup_fresh()
    sk2.config.VECTORIZER_PATH.unlink(missing_ok=True)
    # 让预设路径指向不存在文件，模拟“preset 缺失”
    missing_preset = sk2.DATA_DIR / "no_such_preset.json"
    sk2.scorer.VECTORIZER_PRESET_ST_PATH = missing_preset
    sk2.scorer.set_ollama_available(True)
    cfg = sk2.scorer.ensure_default_vectorizer()
    check("EDGE preset 缺失 → 仍回退 local-tfidf（不崩溃）",
          cfg["backend"] == "local-tfidf", f"backend={cfg.get('backend')}")

    # E3：锁获取超时 → acquired=False（安全跳过，不崩溃）
    sk3 = setup_fresh()
    path = sk3.config.LOCK_PATH
    occ = sk3.filelock.FileLock(path, timeout=2.0)
    occ.__enter__()
    try:
        fl = sk3.filelock.FileLock(path, timeout=0.3)
        with fl:
            acquired = fl.acquired
    finally:
        occ.__exit__(None, None, None)
    check("EDGE 锁占用超时 → acquired=False（安全跳过）", acquired is False,
          f"acquired={acquired}")


# =========================================================================== #
def main() -> int:
    print("=== SkillForge v2.3 灵魂断点 · 独立真实验证（每节独立环境）===")
    verify_a2_heartbeat()
    verify_a1_pressure()
    verify_a3_lowwatermark()
    verify_c1_no_deprecation()
    verify_c2_filelock_skip()
    verify_d_ollama()
    verify_edge_cases()

    passed = sum(1 for c, _, _ in _RESULTS if c)
    total = len(_RESULTS)
    failed = total - passed
    print("")
    print(f"=== 汇总：{passed}/{total} 通过，{failed} 失败 ===")
    for c, name, detail in _RESULTS:
        if not c:
            print(f"  FAIL: {name} -- {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
