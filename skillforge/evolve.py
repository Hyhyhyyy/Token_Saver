"""自进化引擎（GOAL-2 自主运行 + GOAL-3 可追溯）。

把「gold 播种 → 调度模拟 → 冲突沉淀 → 写账本」串成一次编排调用，并支持开机自启
（受开关控制）。同时提供打分器校准器（local-tfidf vs embedding 横向对比）。

设计约束：
- 零新增 pip 依赖（仅 Python 标准库 + 现有 fastapi/uvicorn/pyyaml/tiktoken）。
- 复用不造轮子：gold / simulator / simbank / budget / custom_rules / scorer 现有函数
  全部直接复用，绝不重复实现其内部逻辑。
- 账本统一经 simbank.log_evolution / get_ledger / build_report 写入同一 SQLite 单连接。
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone

from . import config, gold, budget, custom_rules, simulator, simbank
from .skill_parser import scan_skills
from .scorer import get_vectorizer, _load_vectorizer_config, LocalTfidfBackend, EmbeddingBackend


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _now() -> str:
    """ISO-8601 UTC 时间戳（与 simbank._now 同格式，便于字典序比较）。"""
    return datetime.now(timezone.utc).isoformat()


def _heuristic_query(skill: dict) -> str:
    """从 description 首句启发式提取 query（见 arch §7.2）。

    desc -> 以 。/. / 换行 切首句 -> 去填充词 -> 过短或空回退技能名 -> 裁剪 ≤40 字。
    """
    fm = skill.get("frontmatter") or {}
    desc = (fm.get("description") or "").strip()
    first_sentence = re.split(r"[。.\n]", desc)[0].strip() if desc else ""
    query = first_sentence
    # 去填充词（中文/英文营销腔）
    for fw in config.FILLER_WORDS:
        query = query.replace(fw, "")
    query = query.strip()
    if len(query) < 8:
        # 首句过短或 description 为空，回退为技能名（PRD §3.2 / arch §7.2）
        query = skill.get("name") or ""
    return query.strip()[:40]


def _fetch_new_entries(since_iso: str) -> list[dict]:
    """拉取 ts >= since_iso 的账本条目（聚合本轮 run_evolve 写入的所有动作）。"""
    return simbank._evolution_rows(since=since_iso)


def _rank_divergence(local_seq: list[float], emb_seq: list[float]) -> float:
    """两组打分序列的排序分歧（arch §7.3）。

    rank_divergence = mean(|rank_L_i − rank_E_i|) / (n−1)，标量 [0,1]，0=排序完全一致。
    """
    n = len(local_seq)
    if n < 2:
        return 0.0

    def _ordinal_ranks(seq: list[float]) -> list[int]:
        # 按值降序排名（1..n），并列取其在降序序列中的出现位置
        order = sorted(range(n), key=lambda i: -seq[i])
        ranks = [0] * n
        for rank, idx in enumerate(order, start=1):
            ranks[idx] = rank
        return ranks

    rl = _ordinal_ranks(local_seq)
    re_ = _ordinal_ranks(emb_seq)
    mean_diff = sum(abs(rl[i] - re_[i]) for i in range(n)) / n
    return round(mean_diff / (n - 1), 4)


# --------------------------------------------------------------------------- #
# T02 · 进化引擎
# --------------------------------------------------------------------------- #
def bootstrap_gold(force: bool = False,
                   threshold: int = config.GOLD_SEED_THRESHOLD,
                   trigger: str = "auto_bootstrap") -> dict:
    """播种用户真实技能的 gold 样本（GOAL-1 真实信号）。

    覆盖率语义（v2.1.1 修正）：以「已装用户技能是否被现有 gold 覆盖」判定，
    而非旧版「按总 gold 数 >= 阈值」判定——因为 gold.get_gold() 首次调用会自填
    24 条内置样本，旧阈值门永远触发、真实用户技能（GOAL-1）永不播种。
    仅追加 name 不在现有 gold 中的已装技能（幂等，不删不改既有样本）；
    force=True 仅保留参数兼容，语义同样为「只补缺失项」（不会覆盖/删除既有样本）。
    每新增一项都 log_evolution(gold_seed, sid, "", query, trigger)。

    返回 {seeded, skipped, total, samples, note}。
    """
    # v2.1.1 覆盖率语义：先看已装的真实用户技能里哪些还没有 gold 样本
    existing = gold.get_gold()
    installed = scan_skills(dirs=[config.USER_SKILLS_DIR])
    existing_ids = {g["skill_id"] for g in existing}
    missing = [s for s in installed if s["name"] not in existing_ids]

    # 覆盖率门：所有已装技能都已有 gold 样本 → 无需播种（幂等、不重复扫描/写盘）
    if not missing:
        return {
            "seeded": 0,
            "skipped": len(existing_ids & {s["name"] for s in installed}),
            "total": len(existing),
            "samples": [],
            "note": "所有已装技能已有 gold 样本，无需播种",
        }

    # id 分配：从现有 g(\d+) 取最大序号 +1 起，避免与 set_gold 位置默认 id 冲突
    max_n = 0
    for g in existing:
        m = re.match(r"g(\d+)", str(g.get("id", "")))
        if m:
            max_n = max(max_n, int(m.group(1)))

    merged = list(existing)
    seeded: list[dict] = []
    skipped = len(existing_ids & {s["name"] for s in installed})

    for s in missing:
        sid = s["name"]
        query = _heuristic_query(s) or sid
        max_n += 1
        sample = {"id": f"g{max_n:02d}", "query": query, "skill_id": sid}
        merged.append(sample)
        seeded.append(sample)
        existing_ids.add(sid)
        simbank.log_evolution("gold_seed", sid, "", query, trigger, "播种真实技能 gold 样本")

    # 仅当有新增才落盘（set_gold 会校验并覆盖写入）
    if seeded:
        gold.set_gold(merged)

    return {
        "seeded": len(seeded),
        "skipped": skipped,
        "total": len(merged),
        "samples": seeded,
        "note": f"已为 {len(seeded)} 个缺失技能播种 gold 样本（既有样本未改动）",
    }


def _capture_auto_recall(before: dict, after: dict, trigger: str) -> list[dict]:
    """diff 预算覆盖的 target 上移项（arch §7.1 核心难点 1）。

    before/after 为 budget.load_overrides() 返回的 {skill_id: {target, ...}}。
    仅记「target 上移」的自动回调（首次无覆盖 before 记 DESC_TARGET_TOKENS）；
    每上移项 log_evolution(budget_auto_recall, sid, before, after, trigger)。
    返回本轮新写的 ledger 条目列表。
    """
    new_entries: list[dict] = []
    for sid in after:
        after_target = after[sid].get("target")
        if after_target is None:
            continue
        before_entry = before.get(sid)
        before_target = (
            before_entry.get("target")
            if isinstance(before_entry, dict) else config.DESC_TARGET_TOKENS
        )
        if after_target != before_target and after_target > before_target:
            entry = simbank.log_evolution(
                "budget_auto_recall", str(sid),
                str(before_target), str(after_target), trigger, "调度回归自动回调",
            )
            new_entries.append(entry)
    return new_entries


def run_evolve(seed_threshold: int | None = None) -> dict:
    """自主进化引擎主入口（编排层）。

    ① gold 不足先播种；② 跑 F1 调度模拟并 diff 捕获自动回调；
    ③ F3 高相似冲突（sim≥CONFLICT_AUTO_DEPOSIT_THRESHOLD）自动沉淀规则；
    ④ 聚合本轮所有 ledger 写入；⑤ 返回结构化结果。

    返回 {gold, schedule, auto_recalled, deposited_rules, ledger_new, ran_at}。
    """
    run_start = _now()

    # ① 自动播种真实技能 gold（覆盖率自门：仅补 USER_SKILLS_DIR 中缺失项，OBS-1 修复）。
    # bootstrap_gold 现在自判断是否需要播种，无需调用方再按阈值预筛。
    # seed_threshold 仅保留接口兼容，此处不再用于门控。
    gold_seeded = 0
    bg = bootstrap_gold(trigger="evolve_engine")
    gold_seeded = bg["seeded"]

    # ② 跑 F1 调度模拟，前后快照 diff 捕获自动回调（arch §7.1）
    before = budget.load_overrides()
    schedule_result = simulator.run_schedule_sim()
    after = budget.load_overrides()
    auto_recalled_entries = _capture_auto_recall(before, after, "f1_schedule")

    # ③ F3 高相似冲突自动沉淀为自定义校验规则
    deposited_rules: list[dict] = []
    conflicts = simulator.detect_conflicts(threshold=config.CONFLICT_AUTO_DEPOSIT_THRESHOLD)
    for pair in conflicts.get("pairs", []):
        if pair["similarity"] >= config.CONFLICT_AUTO_DEPOSIT_THRESHOLD:
            shared = pair.get("shared_keywords") or []
            kc = shared if shared else [pair["skill_a"], pair["skill_b"]]
            try:
                rule = custom_rules.deposit_custom_rule(kc, pair["suggestion"])
            except ValueError:
                continue
            cluster_json = json.dumps(
                {"skill_a": pair["skill_a"], "skill_b": pair["skill_b"],
                 "keyword_cluster": kc},
                ensure_ascii=False,
            )
            simbank.log_evolution(
                "conflict_rule_deposit", rule["id"], "",
                cluster_json, "f3_conflict", "高相似冲突自动沉淀",
            )
            deposited_rules.append({
                "id": rule["id"],
                "skill_a": pair["skill_a"],
                "skill_b": pair["skill_b"],
                "keyword_cluster": kc,
            })

    # ④ 聚合本轮（ts >= run_start）所有账本写入
    ledger_new = _fetch_new_entries(run_start)

    return {
        "gold": {"seeded": gold_seeded, "total": len(gold.get_gold())},
        "schedule": {
            "accuracy_before": schedule_result["accuracy_before"],
            "accuracy_after": schedule_result["accuracy_after"],
            "regressed_skills": schedule_result["regressed_skills"],
            # 透传 F1 调度模拟的自愈回退说明（缺陷2：embedding 不可达时回退 local-tfidf）
            "note": schedule_result.get("note"),
        },
        "auto_recalled": [
            {"skill_id": e["object"], "before": e["before_val"], "after": e["after_val"]}
            for e in auto_recalled_entries
        ],
        "deposited_rules": deposited_rules,
        "ledger_new": ledger_new,
        "ran_at": run_start,
    }


# --------------------------------------------------------------------------- #
# T03 · 校准器（零依赖，stdlib statistics + 现有 scorer 后端）
# --------------------------------------------------------------------------- #
def calibrate(limit: int = config.CALIBRATION_SAMPLE_PAIRS) -> dict:
    """横向对比 local-tfidf 与 embedding 对同一批技能对的打分分歧（arch §7.3）。

    可用性门：vectorizer.json backend=="embedding" 且 embedding.api_url 非空才可用，
    否则返回 {available:false, reason:"..."}（HTTP 200，前端提示而非报错）。
    embedding 调用失败整体返回 {available:false, reason:"embedding 调用失败:..."} 而非 500。

    成功返回 {available:true, sample_pairs, correlation, rank_divergence,
             top_divergent_pairs, ran_at}。
    """
    # 可用性门
    cfg = _load_vectorizer_config()
    emb = cfg.get("embedding", {}) or {}
    if cfg.get("backend") != "embedding" or not emb.get("api_url"):
        return {
            "available": False,
            "reason": "embedding 后端未配置 api_url，无法横向对比；当前仅 local-tfidf",
        }

    try:
        local = LocalTfidfBackend()
        emb_backend = EmbeddingBackend(api_url=emb["api_url"])

        descs = [
            (s["name"], s["frontmatter"].get("description") or "")
            for s in scan_skills()
        ]
        descs = [d for d in descs if d[1]]  # 仅保留有 description 的技能
        if len(descs) < 2:
            return {
                "available": True,
                "sample_pairs": 0,
                "correlation": None,
                "rank_divergence": None,
                "top_divergent_pairs": [],
                "ran_at": _now(),
                "note": "技能描述不足，无法成对采样",
            }

        # 所有技能对用 local-tfidf 打分，取相似度最高的前 limit 对（D4：保证区分度）
        all_pairs = []
        for i in range(len(descs)):
            for j in range(i + 1, len(descs)):
                a, da = descs[i]
                b, db = descs[j]
                sim_local = local.similarity(da, db)
                all_pairs.append((a, b, da, db, sim_local))
        all_pairs.sort(key=lambda p: -p[4])
        top = all_pairs[:limit]

        sim_local_seq: list[float] = []
        sim_emb_seq: list[float] = []
        sample_pairs: list[dict] = []
        for (a, b, da, db, sl) in top:
            se = emb_backend.similarity(da, db)
            sim_local_seq.append(sl)
            sim_emb_seq.append(se)
            sample_pairs.append({
                "skill_a": a,
                "skill_b": b,
                "sim_local": round(sl, 4),
                "sim_emb": round(se, 4),
                "diff": round(abs(sl - se), 4),
            })

        # 相关性（Pearson）：任一方差为零 → corr=None 并备注（arch §7.3）
        corr: float | None = None
        corr_note = ""
        try:
            var_l = statistics.pvariance(sim_local_seq)
            var_e = statistics.pvariance(sim_emb_seq)
            if var_l == 0 or var_e == 0:
                corr = None
                corr_note = "序列无方差，相关性无意义"
            else:
                corr = round(statistics.correlation(sim_local_seq, sim_emb_seq), 4)
        except statistics.StatisticsError:
            corr = None
            corr_note = "相关性计算失败（方差为零）"

        rank_div = _rank_divergence(sim_local_seq, sim_emb_seq)

        # 取 |sim_local − sim_emb| 最大的前 5 对（arch §7.3）
        top_div = sorted(sample_pairs, key=lambda p: -p["diff"])[:5]

        simbank.log_evolution(
            "calibration", "scorer", "",
            f"corr={corr};rank_div={rank_div}" + (f";{corr_note}" if corr_note else ""),
            "manual", "校准打分器分歧度记录",
        )

        return {
            "available": True,
            "sample_pairs": len(sample_pairs),
            "correlation": corr,
            "rank_divergence": rank_div,
            "top_divergent_pairs": top_div,
            "ran_at": _now(),
        }
    except Exception as e:  # noqa: BLE001
        # embedding 调用失败：整体返回 available:false 而非 500（arch §7.3 / R-embedding）
        return {"available": False, "reason": f"embedding 调用失败: {e}"}
