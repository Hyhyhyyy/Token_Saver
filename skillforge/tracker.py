"""调用效果追踪：基于 SQLite 记录优化动作与调用事件，支撑 dashboard 聚合。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    action TEXT NOT NULL,
    tokens_before INTEGER DEFAULT 0,
    tokens_after INTEGER DEFAULT 0,
    saved INTEGER DEFAULT 0,
    note TEXT,
    ts TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def log_event(skill_id: str, action: str, tokens_before: int = 0,
              tokens_after: int = 0, note: str = "") -> int:
    saved = max(0, tokens_before - tokens_after)
    ts = datetime.now(timezone.utc).isoformat()
    c = _conn()
    cur = c.execute(
        "INSERT INTO events (skill_id, action, tokens_before, tokens_after, saved, note, ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (skill_id, action, tokens_before, tokens_after, saved, note, ts),
    )
    c.commit()
    c.close()
    return cur.lastrowid


def get_stats() -> dict:
    c = _conn()
    total_events = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    total_saved = c.execute("SELECT COALESCE(SUM(saved),0) AS s FROM events").fetchone()["s"]
    applied = c.execute(
        "SELECT COUNT(DISTINCT skill_id) AS n FROM events WHERE action='apply'"
    ).fetchone()["n"]
    by_action = {}
    for row in c.execute("SELECT action, COUNT(*) AS n, COALESCE(SUM(saved),0) AS s "
                         "FROM events GROUP BY action"):
        by_action[row["action"]] = {"count": row["n"], "saved": row["s"]}
    c.close()
    # 每轮节省：所有 apply 事件的单技能 desc 节省之和（常驻上下文每轮都省）
    per_turn = c2_per_turn_saving()
    return {
        "total_events": total_events,
        "total_saved": total_saved,
        "applied_skills": applied,
        "by_action": by_action,
        "per_turn_saving": per_turn,
    }


def c2_per_turn_saving() -> int:
    """已应用技能在 description 维度上的每轮累计节省（常驻上下文）。"""
    c = _conn()
    rows = c.execute(
        "SELECT skill_id, MAX(tokens_before)-MAX(tokens_after) AS delta FROM events "
        "WHERE action='apply' GROUP BY skill_id"
    ).fetchall()
    c.close()
    return sum(max(0, r["delta"]) for r in rows)


def get_skill_stats(skill_id: str) -> dict:
    c = _conn()
    rows = c.execute(
        "SELECT action, COUNT(*) AS n, COALESCE(SUM(saved),0) AS s, MAX(ts) AS last "
        "FROM events WHERE skill_id=? GROUP BY action", (skill_id,)
    ).fetchall()
    c.close()
    return {r["action"]: {"count": r["n"], "saved": r["s"], "last": r["last"]} for r in rows}


def get_series() -> list[dict]:
    """按天聚合节省与事件数，供趋势图使用。"""
    c = _conn()
    rows = c.execute(
        "SELECT substr(ts,1,10) AS day, COALESCE(SUM(saved),0) AS saved, COUNT(*) AS events "
        "FROM events GROUP BY day ORDER BY day"
    ).fetchall()
    c.close()
    return [{"day": r["day"], "saved": r["saved"], "events": r["events"]} for r in rows]


def get_leaderboard() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT skill_id, COALESCE(SUM(saved),0) AS saved, COUNT(*) AS events "
        "FROM events GROUP BY skill_id ORDER BY saved DESC LIMIT 20"
    ).fetchall()
    c.close()
    return [{"skill_id": r["skill_id"], "saved": r["saved"], "events": r["events"]} for r in rows]
