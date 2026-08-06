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
