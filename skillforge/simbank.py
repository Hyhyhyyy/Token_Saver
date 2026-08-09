"""仿真结果持久化（复用 config.DB_PATH 同库，新增三表）。

- scheduling_sim：每次 F1 调度模拟一行。
- cost_sim：每次 F2 成本/延迟仿真一行。
- sim_regressions：回归技能累计表（闭环：累计≥2 自动回调预算）。
沿用 tracker 的单连接 executescript 建表模式，不改动 events 表。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH
from . import budget

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduling_sim (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    accuracy_before  REAL,
    accuracy_after   REAL,
    regressed_skills TEXT,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS cost_sim (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,
    model               TEXT,
    skills_count        INTEGER,
    turns               INTEGER,
    resident_before     INTEGER,
    resident_after      INTEGER,
    cost_before         REAL,
    cost_after          REAL,
    saved_amount        REAL,
    latency_before      REAL,
    latency_after       REAL,
    saved_latency       REAL
);

CREATE TABLE IF NOT EXISTS sim_regressions (
    skill_id     TEXT PRIMARY KEY,
    count        INTEGER NOT NULL DEFAULT 0,
    last_target  INTEGER,
    updated_at   TEXT
);

-- 进化账本（v2.1 新增）：统一记录每一次自进化动作（GOAL-3 可追溯）
CREATE TABLE IF NOT EXISTS evolution_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    action_type TEXT NOT NULL,
    object      TEXT,
    before_val  TEXT,
    after_val   TEXT,
    trigger     TEXT,
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_ledger_ts        ON evolution_ledger(ts);
CREATE INDEX IF NOT EXISTS idx_ledger_action    ON evolution_ledger(action_type);
CREATE INDEX IF NOT EXISTS idx_ledger_object    ON evolution_ledger(object);

-- 进化趋势采集（v2.2 新增 · C-1）：每次 run_evolve 写一行覆盖度 / F1 选对率
CREATE TABLE IF NOT EXISTS evolution_metrics (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    gold_coverage  REAL,
    f1_acc_before  REAL,
    f1_acc_after   REAL
);

CREATE INDEX IF NOT EXISTS idx_metrics_ts ON evolution_metrics(ts);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def log_schedule_sim(accuracy_before: float, accuracy_after: float,
                     regressed_skills: list, note: str = "") -> int:
    c = _conn()
    cur = c.execute(
        "INSERT INTO scheduling_sim (ts, accuracy_before, accuracy_after, regressed_skills, note) "
        "VALUES (?,?,?,?,?)",
        (_now(), accuracy_before, accuracy_after,
         json.dumps(regressed_skills, ensure_ascii=False), note),
    )
    c.commit()
    c.close()
    return cur.lastrowid


def log_cost_sim(model, skills_count, turns, resident_before, resident_after,
                 cost_before, cost_after, saved_amount,
                 latency_before, latency_after, saved_latency) -> int:
    c = _conn()
    cur = c.execute(
        "INSERT INTO cost_sim (ts, model, skills_count, turns, resident_before, resident_after, "
        "cost_before, cost_after, saved_amount, latency_before, latency_after, saved_latency) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (_now(), model, skills_count, turns, resident_before, resident_after,
         cost_before, cost_after, saved_amount, latency_before, latency_after, saved_latency),
    )
    c.commit()
    c.close()
    return cur.lastrowid


def bump_regression(skill_id: str) -> int:
    """回归计数 +1，返回新的累计次数（同时记录当前 effective_target 作为 last_target）。"""
    c = _conn()
    row = c.execute("SELECT count FROM sim_regressions WHERE skill_id=?", (skill_id,)).fetchone()
    if row:
        new_count = row["count"] + 1
        c.execute(
            "UPDATE sim_regressions SET count=?, last_target=?, updated_at=? WHERE skill_id=?",
            (new_count, budget.effective_target(skill_id), _now(), skill_id),
        )
    else:
        new_count = 1
        c.execute(
            "INSERT INTO sim_regressions (skill_id, count, last_target, updated_at) VALUES (?,?,?,?)",
            (skill_id, new_count, budget.effective_target(skill_id), _now()),
        )
    c.commit()
    c.close()
    return new_count


def get_regression(skill_id: str) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT skill_id, count, last_target, updated_at FROM sim_regressions WHERE skill_id=?",
        (skill_id,),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_schedule_trend(limit: int = 30) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ts, accuracy_before, accuracy_after, regressed_skills FROM scheduling_sim "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        out.append({
            "ts": r["ts"],
            "accuracy_before": r["accuracy_before"],
            "accuracy_after": r["accuracy_after"],
            "regressed_skills": json.loads(r["regressed_skills"] or "[]"),
        })
    return out


def get_cost_trend(limit: int = 30) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ts, model, saved_amount, cost_before, cost_after FROM cost_sim "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ============================================================
# 进化账本（v2.1 新增 · GOAL-3 可追溯）
# 复用同一 _conn() 单连接，不改动 v2.0 三张表。
# ============================================================

def log_evolution(action_type: str, object: str, before_val: str,
                  after_val: str, trigger: str, note: str = "") -> dict:
    """写一行 evolution_ledger，返回该行 dict（含自增 id、ts）。"""
    c = _conn()
    cur = c.execute(
        "INSERT INTO evolution_ledger (ts, action_type, object, before_val, after_val, trigger, note) "
        "VALUES (?,?,?,?,?,?,?)",
        (_now(), action_type, object, before_val, after_val, trigger, note),
    )
    row = c.execute(
        "SELECT * FROM evolution_ledger WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    c.commit()
    c.close()
    return dict(row)


def get_ledger(limit: int = 50, action_type: str | None = None,
               object: str | None = None,
               since: str | None = None,
               until: str | None = None) -> dict:
    """分页 + 过滤查询进化账本（C-2：新增 since/until 时间窗过滤）。

    返回 {count, entries:[{id,ts,action_type,object,before_val,after_val,trigger,note}]}。
    limit 夹紧到 [1,200]；action_type/object/since/until 为空表示不过滤；
    since/until 为 ISO 字符串（可直接按字典序比较）；按 ts DESC、id DESC。
    """
    limit = max(1, min(200, int(limit)))
    clauses = []
    params: list = []
    if action_type is not None:
        clauses.append("action_type = ?")
        params.append(action_type)
    if object is not None:
        clauses.append("object = ?")
        params.append(object)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ts <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    c = _conn()
    rows = c.execute(
        "SELECT * FROM evolution_ledger" + where +
        " ORDER BY ts DESC, id DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    c.close()
    entries = [dict(r) for r in rows]
    return {"count": len(entries), "entries": entries}


def log_evolution_metric(gold_coverage: float, f1_acc_before: float,
                         f1_acc_after: float) -> dict:
    """写一行 evolution_metrics（C-1），返回该行 dict（含自增 id、ts）。

    由 evolve.run_evolve 在每次（非 no-op）运行末调用，记录：
    gold_coverage（0~100，已装用户技能被 gold 覆盖的百分比）、
    f1_acc_before / f1_acc_after（F1 调度模拟清洗前/后选对率，0~1）。
    """
    c = _conn()
    cur = c.execute(
        "INSERT INTO evolution_metrics (ts, gold_coverage, f1_acc_before, f1_acc_after) "
        "VALUES (?,?,?,?)",
        (_now(), float(gold_coverage), float(f1_acc_before), float(f1_acc_after)),
    )
    row = c.execute(
        "SELECT * FROM evolution_metrics WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    c.commit()
    c.close()
    return dict(row)


def get_evolution_metrics(limit: int = 100) -> list[dict]:
    """返回进化趋势采集点（C-1），按 ts ASC（前端折线按时间升序绘制）。

    limit 夹紧 [1,1000]；每点 {ts, gold_coverage, f1_acc_before, f1_acc_after}。
    """
    limit = max(1, min(1000, int(limit)))
    c = _conn()
    rows = c.execute(
        "SELECT ts, gold_coverage, f1_acc_before, f1_acc_after "
        "FROM evolution_metrics ORDER BY ts ASC, id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_last_evolution_metric() -> dict | None:
    """返回 evolution_metrics 最新一行（A-5 节流用，id DESC LIMIT 1）。

    返回 {id, ts, gold_coverage, f1_acc_before, f1_acc_after}；无数据返回 None。
    ts 为 UTC ISO-8601（与 simbank._now 同格式，可经 datetime.fromisoformat 解析）。
    """
    c = _conn()
    row = c.execute(
        "SELECT id, ts, gold_coverage, f1_acc_before, f1_acc_after "
        "FROM evolution_metrics ORDER BY id DESC LIMIT 1"
    ).fetchone()
    c.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "ts": row["ts"],
        "gold_coverage": row["gold_coverage"],
        "f1_acc_before": row["f1_acc_before"],
        "f1_acc_after": row["f1_acc_after"],
    }


def _evolution_rows(since: str | None = None, until: str | None = None,
                    limit: int | None = None) -> list[dict]:
    """按时间窗（ISO 字符串）拉取账本行，ISO 字符串可直接按字典序比较。"""
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ts <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    q = "SELECT * FROM evolution_ledger" + where + " ORDER BY ts DESC, id DESC"
    if limit is not None:
        q += " LIMIT ?"
        params.append(int(limit))
    c = _conn()
    rows = c.execute(q, params).fetchall()
    c.close()
    return [dict(r) for r in rows]


def build_report(format: str = "markdown", since: str | None = None,
                 until: str | None = None) -> str | dict:
    """按时间窗汇总进化账本。

    format='json'  → {generated_at, summary:{total, by_action_type}, entries}
    format='markdown' → 标题 + 各 action_type 计数表 + 时间线列表（供前端 Blob 下载）。
    """
    rows = _evolution_rows(since, until)
    by_action_type: dict[str, int] = {}
    for r in rows:
        by_action_type[r["action_type"]] = by_action_type.get(r["action_type"], 0) + 1
    summary = {"total": len(rows), "by_action_type": by_action_type}
    generated_at = _now()

    if format == "json":
        return {"generated_at": generated_at, "summary": summary, "entries": rows}

    lines: list[str] = []
    lines.append("# SkillForge 进化报告（Evolution Report）")
    lines.append("")
    lines.append(f"- 生成时间：{generated_at}")
    if since or until:
        lines.append(f"- 时间窗：{since or '起点'} ~ {until or '现在'}")
    lines.append(f"- 动作总数：{summary['total']}")
    lines.append("")
    lines.append("## 动作类型计数")
    lines.append("")
    lines.append("| 动作类型 | 数量 |")
    lines.append("| --- | --- |")
    if by_action_type:
        for at, cnt in sorted(by_action_type.items(), key=lambda x: -x[1]):
            lines.append(f"| {at} | {cnt} |")
    else:
        lines.append("| （无） | 0 |")
    lines.append("")
    lines.append("## 进化时间线")
    lines.append("")
    if not rows:
        lines.append("（无记录）")
    else:
        for r in rows:
            line = (
                f"- [{r['ts']}] **{r['action_type']}** · 对象 `{r['object'] or ''}` · "
                f"值 `{r['before_val'] or ''}` → `{r['after_val'] or ''}` · 触发 `{r['trigger']}`"
            )
            if r["note"]:
                line += f" · {r['note']}"
            lines.append(line)
    return "\n".join(lines)
