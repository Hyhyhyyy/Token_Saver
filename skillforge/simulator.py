"""三大仿真/冲突引擎 + 自进化闭环逻辑（F1/F2/F3）。

- F1 run_schedule_sim：同一向量化器下，分别对「清洗前 description 列表」与「清洗后
  description 列表」模拟 Agent 选最相关技能，控制变量仅 description 版本不同。
  统计整体选对率 before/after、逐技能命中、regressed_skills；并写 simbank、
  对 regressed 技能累计回归，≥BUDGET_RECALL_TRIGGER 自动回调预算（注入 cleaner）。
- F2 run_cost_sim：输入 model/skills_count/turns/resident_tokens 推演每轮常驻、累计
  token、折算金额与延迟；写 simbank。
- F3 detect_conflicts：跨技能对所有 description 两两向量相似度，超阈值标记冲突对。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .skill_parser import scan_skills
from .cleaner import clean_description
from .scorer import get_vectorizer, LocalTfidfBackend, conflict_default_threshold
from . import gold, budget, pricing, simbank
from .config import (
    CONFLICT_THRESHOLD_MIN,
    CONFLICT_THRESHOLD_MAX,
    BUDGET_RECALL_TRIGGER,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _argmax(descs: dict, query: str, vec) -> str:
    """在 descs 中取与 query 打分最高者；按技能名排序保证确定性（并列取字典序最小）。"""
    best, best_score = None, -1.0
    for sk in sorted(descs):
        sc = vec.score(query, descs[sk])
        if sc > best_score:
            best_score, best = sc, sk
    return best


def _resolve_vectorizer(backend_name: str | None,
                        probe_a: str = "",
                        probe_b: str = "") -> tuple:
    """取得打分器，并对 embedding 后端做探活（缺陷2 自愈）。

    embedding 后端在 score()/similarity() 时才真正发起远程调用；若探活抛异常
    （api_url 错误 / 网络不可达 / 超时），自动回退 LocalTfidfBackend 完成本次
    模拟/冲突检测，绝不向上抛 500。仅当 probe_a/probe_b 均非空时才探活（避免无
    数据时多余的网络调用）。get_vectorizer 默认 local-tfidf 时直接返回。

    返回 (vec, note)；note 非空表示发生了回退。
    """
    vec = get_vectorizer(backend_name)
    note = ""
    if vec.__class__.__name__ == "EmbeddingBackend" and probe_a and probe_b:
        try:
            vec.score(probe_a, probe_b)
        except Exception:  # noqa: BLE001
            vec = LocalTfidfBackend()
            note = "embedding 不可用，已回退 local-tfidf"
    return vec, note


def run_schedule_sim(backend_name: str | None = None, use_llm: bool = False) -> dict:
    """运行调度反事实模拟，返回 before/after 准确率、逐技能命中、回归清单。"""
    samples = gold.get_gold()
    skills = scan_skills()

    # 构建两版 description：before=当前；after=cleaner 清洗后（按 effective_target）
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    for s in skills:
        desc = s["frontmatter"].get("description") or ""
        before[s["name"]] = desc
        cleaned, _ = clean_description(desc, budget.effective_target(s["name"]))
        after[s["name"]] = cleaned

    # 仅评估「正确技能在当前技能集中」的 gold 样本（R2：缺失技能样本跳过并标注）
    # 不在当前技能集的 gold 样本被跳过，不计入 accuracy 分母，并在响应中标注原因
    matched = [g for g in samples if g["skill_id"] in before]
    skipped_detail = [
        {
            "skill_id": g["skill_id"],
            "query": g["query"],
            "reason": "gold skill 不在当前扫描技能集",
        }
        for g in samples
        if g["skill_id"] not in before
    ]
    total = len(matched)

    # 构造打分器（缺陷2 自愈：embedding 不可达自动回退 local-tfidf，绝不 500）
    corpus = list(before.values()) + [g["query"] for g in matched]
    if matched:
        vec, note = _resolve_vectorizer(
            backend_name, matched[0]["query"], before[matched[0]["skill_id"]]
        )
    else:
        vec = get_vectorizer(backend_name)
        note = ""
    vec.fit(corpus)

    hits_before: dict[str, int] = defaultdict(int)
    hits_after: dict[str, int] = defaultdict(int)
    correct_before = correct_after = 0
    for g in matched:
        q, sid = g["query"], g["skill_id"]
        if _argmax(before, q, vec) == sid:
            correct_before += 1
            hits_before[sid] += 1
        if _argmax(after, q, vec) == sid:
            correct_after += 1
            hits_after[sid] += 1

    accuracy_before = correct_before / total if total else 0.0
    accuracy_after = correct_after / total if total else 0.0

    gold_skills = sorted({g["skill_id"] for g in matched})
    per_skill = []
    for sk in gold_skills:
        hb, ha = hits_before[sk], hits_after[sk]
        delta = ha - hb
        status = "improved" if delta > 0 else ("regressed" if delta < 0 else "unchanged")
        per_skill.append({
            "skill_id": sk,
            "hits_before": hb,
            "hits_after": ha,
            "delta": delta,
            "status": status,
        })

    regressed = [sk for sk in gold_skills if hits_after[sk] < hits_before[sk]]
    regressed_skills = [
        {
            "skill_id": sk,
            "hits_before": hits_before[sk],
            "hits_after": hits_after[sk],
            "suggestion": "建议回调该技能压缩预算",
        }
        for sk in regressed
    ]

    # 持久化 + 闭环：累计回归，达阈值自动回调预算
    simbank.log_schedule_sim(accuracy_before, accuracy_after,
                             [r["skill_id"] for r in regressed_skills])
    for sk in regressed:
        count = simbank.bump_regression(sk)
        if count >= BUDGET_RECALL_TRIGGER:
            budget.auto_recall(sk)

    # 全部样本都被跳过（当前技能集与内置 gold 样本无交集）时的明确提示
    if total == 0:
        message = (
            "当前技能集与内置 gold 样本无交集，请到仿真沙盘导入自定义 gold 样本"
            "（导入与技能集匹配的 query→skill_id 映射）后再评估"
        )
    else:
        message = ""

    return {
        "accuracy_before": round(accuracy_before, 4),
        "accuracy_after": round(accuracy_after, 4),
        "evaluated_samples": total,
        "skipped": len(skipped_detail),
        "skipped_samples": len(skipped_detail),
        "skipped_detail": skipped_detail,
        "per_skill": per_skill,
        "regressed_skills": regressed_skills,
        "message": message,
        "note": note,
        "ran_at": _now(),
    }


def run_cost_sim(model: str, skills_count: int, turns: int,
                 resident_tokens_before: int,
                 resident_tokens_after: int | None = None) -> dict:
    """运行成本/延迟仿真，返回每轮常驻、累计 token、金额与延迟对比。"""
    table = pricing.get_pricing()
    row = next((m for m in table["models"] if m["model"] == model), None)
    if row is None:
        raise ValueError(f"未知模型：{model}")

    after = resident_tokens_before if resident_tokens_after is None else resident_tokens_after
    turns = int(turns)
    rb = int(resident_tokens_before)
    ra = int(after)

    cumulative_before = rb * turns
    cumulative_after = ra * turns

    ip = float(row.get("input_price_per_1k", 0))
    cost_before = cumulative_before / 1000.0 * ip
    cost_after = cumulative_after / 1000.0 * ip
    saved_amount = cost_before - cost_after

    overhead = float(row.get("latency_overhead_ms", 0))
    per_token = float(row.get("latency_per_token_ms", 0))
    latency_per_round_before = overhead + rb * per_token
    latency_per_round_after = overhead + ra * per_token
    latency_cumulative_before = turns * latency_per_round_before
    latency_cumulative_after = turns * latency_per_round_after
    saved_latency = latency_cumulative_before - latency_cumulative_after

    simbank.log_cost_sim(
        model, int(skills_count), turns, rb, ra,
        cost_before, cost_after, saved_amount,
        latency_per_round_before, latency_per_round_after, saved_latency,
    )

    return {
        "per_round_resident_before": rb,
        "per_round_resident_after": ra,
        "cumulative_before": cumulative_before,
        "cumulative_after": cumulative_after,
        "cost_before": round(cost_before, 6),
        "cost_after": round(cost_after, 6),
        "saved_amount": round(saved_amount, 6),
        "latency_per_round_before": round(latency_per_round_before, 4),
        "latency_per_round_after": round(latency_per_round_after, 4),
        "latency_cumulative_before": round(latency_cumulative_before, 4),
        "latency_cumulative_after": round(latency_cumulative_after, 4),
        "saved_latency": round(saved_latency, 4),
    }


def _backend_label(vec) -> str:
    return "embedding" if vec.__class__.__name__ == "EmbeddingBackend" else "local-tfidf"


def detect_conflicts(threshold: float | None = None,
                     backend_name: str | None = None) -> dict:
    """跨技能对所有 description 两两向量相似度，超阈值标记冲突对。

    默认阈值经 scorer.conflict_default_threshold() 取用，随后端分档
    （embedding 档 0.55 / local-tfidf 档 0.7，A-2）。
    """
    if threshold is None:
        threshold = conflict_default_threshold()
    threshold = min(CONFLICT_THRESHOLD_MAX, max(CONFLICT_THRESHOLD_MIN, float(threshold)))

    skills = scan_skills()
    items = [(s["name"], s["frontmatter"].get("description") or "") for s in skills]

    # 缺陷2 自愈：embedding 不可达时回退 local-tfidf（避免 /api/conflicts 与
    # run_evolve 走 embedding 时抛 500）。用首个「两描述均非空」的真实技能对做探活，
    # 并保留 note 透传给调用方（前端/排查可观测回退）。
    note = ""
    if items:
        probe_a, probe_b = "", ""
        for i, (a, da) in enumerate(items):
            for j in range(i + 1, len(items)):
                b, db = items[j]
                if da and db:
                    probe_a, probe_b = da, db
                    break
            if probe_a:
                break
        vec, note = _resolve_vectorizer(backend_name, probe_a, probe_b)
    else:
        vec = get_vectorizer(backend_name)
    vec.fit([d for _, d in items])

    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, da = items[i]
            b, db = items[j]
            if not da or not db:
                continue
            sim = vec.similarity(da, db)
            if sim >= threshold:
                shared = vec.shared_keywords(da, db)
                suggestion = (
                    "建议合并（能力高度重叠）"
                    if sim > 0.85
                    else "建议差异化定位（前者偏编辑、后者偏生成）或合并"
                )
                pairs.append({
                    "skill_a": a,
                    "skill_b": b,
                    "similarity": round(sim, 4),
                    "shared_keywords": shared,
                    "suggestion": suggestion,
                })
    pairs.sort(key=lambda p: -p["similarity"])
    return {
        "threshold": round(threshold, 4),
        "backend": _backend_label(vec),
        "pairs": pairs,
        "note": note,
    }
