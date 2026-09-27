"""
Database layer - SQLite persistence for runs, workflows, and records.

Tables:
  runs(id, prompt, intent_json, workflow_json, status, total_records,
       created_at, finished_at)
  records(id, run_id, source, type, title, description, url, company, location,
          skills_json, industries_json, published_at, score, extra_json)
"""

from __future__ import annotations
import sqlite3
import json
import time
import os
import threading
from typing import List, Dict, Any, Optional


_DB_LOCK = threading.Lock()
DB_PATH = os.environ.get(
    "DIP_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "platform.db"),
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                intent_json TEXT,
                workflow_json TEXT,
                status TEXT,
                total_records INTEGER DEFAULT 0,
                created_at REAL,
                finished_at REAL
            );
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source TEXT,
                type TEXT,
                title TEXT,
                description TEXT,
                url TEXT,
                company TEXT,
                location TEXT,
                skills_json TEXT,
                industries_json TEXT,
                published_at TEXT,
                score INTEGER,
                extra_json TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_records_run ON records(run_id);
            CREATE INDEX IF NOT EXISTS idx_records_type ON records(type);
            CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);

            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_run_id TEXT,
                next_run_at REAL,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS webhooks (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                type TEXT NOT NULL,  -- slack | discord | generic
                event TEXT NOT NULL, -- run_done | run_failed
                enabled INTEGER DEFAULT 1,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS share_links (
                token TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                created_at REAL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS source_health (
                source TEXT PRIMARY KEY,
                last_status TEXT,
                last_latency_ms INTEGER,
                last_record_count INTEGER,
                last_checked REAL,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                total_latency_ms INTEGER DEFAULT 0
            );
            """)
            conn.commit()
        finally:
            conn.close()


def save_run(run: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO runs
                   (id, prompt, intent_json, workflow_json, status, total_records, created_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["id"],
                    run["prompt"],
                    json.dumps(run.get("intent", {})),
                    json.dumps(run.get("workflow", {})),
                    run.get("status", "done"),
                    run.get("total_records", len(records)),
                    run.get("created_at", time.time()),
                    run.get("finished_at", time.time()),
                ),
            )

            # Wipe existing records for this run (idempotent re-save)
            cur.execute("DELETE FROM records WHERE run_id = ?", (run["id"],))

            for r in records:
                cur.execute(
                    """INSERT OR REPLACE INTO records
                       (id, run_id, source, type, title, description, url, company, location,
                        skills_json, industries_json, published_at, score, extra_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        r.get("id"),
                        run["id"],
                        r.get("source"),
                        r.get("type"),
                        r.get("title"),
                        r.get("description"),
                        r.get("url"),
                        r.get("company"),
                        r.get("location"),
                        json.dumps(r.get("skills") or []),
                        json.dumps(r.get("industries") or []),
                        r.get("published_at"),
                        int(r.get("score") or 0),
                        json.dumps(r.get("extra") or {}),
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def create_run(run_id: str, prompt: str) -> None:
    """Insert a placeholder run row before execution starts."""
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO runs (id, prompt, status, created_at) VALUES (?, ?, ?, ?)",
                (run_id, prompt, "running", time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def update_run_status(run_id: str, status: str, error: Optional[str] = None) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            if error:
                cur.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, intent_json = COALESCE(intent_json, '{}') WHERE id = ?",
                    (status, time.time(), run_id),
                )
            else:
                cur.execute(
                    "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                    (status, time.time(), run_id),
                )
            conn.commit()
        finally:
            conn.close()


def list_runs() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 100")
            rows = cur.fetchall()
            return [_row_to_run_summary(dict(r)) for r in rows]
        finally:
            conn.close()


def get_run_detail(run_id: str) -> Optional[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            r = cur.fetchone()
            if not r:
                return None
            run = dict(r)
            run["intent"] = json.loads(run.pop("intent_json") or "{}")
            run["workflow"] = json.loads(run.pop("workflow_json") or "{}")
            return run
        finally:
            conn.close()


def list_records(
    run_id: str,
    q: Optional[str] = None,
    source: Optional[str] = None,
    min_score: Optional[int] = None,
    sort: str = "score_desc",
    limit: int = 200,
) -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            sql = "SELECT * FROM records WHERE run_id = ?"
            params: List[Any] = [run_id]
            if q:
                sql += " AND (title LIKE ? OR description LIKE ? OR company LIKE ?)"
                like = f"%{q}%"
                params.extend([like, like, like])
            if source:
                sql += " AND source = ?"
                params.append(source)
            if min_score is not None:
                sql += " AND score >= ?"
                params.append(min_score)
            if sort == "score_desc":
                sql += " ORDER BY score DESC"
            elif sort == "score_asc":
                sql += " ORDER BY score ASC"
            elif sort == "newest":
                sql += " ORDER BY published_at DESC"
            elif sort == "oldest":
                sql += " ORDER BY published_at ASC"
            else:
                sql += " ORDER BY score DESC"
            sql += " LIMIT ?"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_record(dict(r)) for r in rows]
        finally:
            conn.close()


def distinct_sources(run_id: str) -> List[str]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT source FROM records WHERE run_id = ? ORDER BY source",
                (run_id,),
            )
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()


def stats() -> Dict[str, Any]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM runs")
            runs_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM records")
            records_count = cur.fetchone()["c"]
            cur.execute("SELECT type, COUNT(*) AS c FROM records GROUP BY type")
            by_type = {r["type"]: r["c"] for r in cur.fetchall()}
            cur.execute("SELECT source, COUNT(*) AS c FROM records GROUP BY source")
            by_source = {r["source"]: r["c"] for r in cur.fetchall()}
            return {
                "runs": runs_count,
                "records": records_count,
                "by_type": by_type,
                "by_source": by_source,
            }
        finally:
            conn.close()


def delete_run(run_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM records WHERE run_id = ?", (run_id,))
            cur.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            conn.commit()
            return cur.rowcount > 0 or True
        finally:
            conn.close()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _row_to_run_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "prompt": row["prompt"],
        "intent": _safe_json(row.get("intent_json")),
        "status": row["status"],
        "total_records": row["total_records"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def _row_to_record(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "source": row["source"],
        "type": row["type"],
        "title": row["title"],
        "description": row["description"],
        "url": row["url"],
        "company": row["company"],
        "location": row["location"],
        "skills": _safe_json(row.get("skills_json")) or [],
        "industries": _safe_json(row.get("industries_json")) or [],
        "published_at": row["published_at"],
        "score": row["score"],
        "extra": _safe_json(row.get("extra_json")) or {},
    }


def _safe_json(s: Any) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


# ----------------------------------------------------------------------
# Schedules
# ----------------------------------------------------------------------

def create_schedule(schedule_id: str, prompt: str, interval_seconds: int, next_run_at: float) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO schedules (id, prompt, interval_seconds, enabled, next_run_at, created_at)
                   VALUES (?, ?, ?, 1, ?, ?)""",
                (schedule_id, prompt, interval_seconds, next_run_at, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def list_schedules() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM schedules ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_due_schedules(now: float) -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ?", (now,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def update_schedule_after_run(schedule_id: str, last_run_id: str, next_run_at: float) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE schedules SET last_run_id = ?, next_run_at = ? WHERE id = ?",
                (last_run_id, next_run_at, schedule_id),
            )
            conn.commit()
        finally:
            conn.close()


def delete_schedule(schedule_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def toggle_schedule(schedule_id: str, enabled: bool) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id))
            conn.commit()
        finally:
            conn.close()


# ----------------------------------------------------------------------
# Webhooks
# ----------------------------------------------------------------------

def create_webhook(webhook_id: str, url: str, type_: str, event: str) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO webhooks (id, url, type, event, enabled, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (webhook_id, url, type_, event, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def list_webhooks() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM webhooks ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_active_webhooks(event: str) -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM webhooks WHERE enabled = 1 AND event = ?", (event,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def delete_webhook(webhook_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ----------------------------------------------------------------------
# Share links
# ----------------------------------------------------------------------

def create_share_link(token: str, run_id: str) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO share_links (token, run_id, created_at) VALUES (?, ?, ?)",
                (token, run_id, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def get_run_by_share_token(token: str) -> Optional[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT r.* FROM runs r JOIN share_links s ON r.id = s.run_id WHERE s.token = ?",
                (token,),
            )
            r = cur.fetchone()
            if not r:
                return None
            run = dict(r)
            run["intent"] = json.loads(run.pop("intent_json") or "{}")
            run["workflow"] = json.loads(run.pop("workflow_json") or "{}")
            return run
        finally:
            conn.close()


# ----------------------------------------------------------------------
# Source health
# ----------------------------------------------------------------------

def update_source_health(source: str, status: str, latency_ms: int, record_count: int) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO source_health (source, last_status, last_latency_ms, last_record_count,
                                              last_checked, success_count, fail_count, total_latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                     last_status = excluded.last_status,
                     last_latency_ms = excluded.last_latency_ms,
                     last_record_count = excluded.last_record_count,
                     last_checked = excluded.last_checked,
                     success_count = success_count + excluded.success_count,
                     fail_count = fail_count + excluded.fail_count,
                     total_latency_ms = total_latency_ms + excluded.total_latency_ms""",
                (
                    source, status, latency_ms, record_count, time.time(),
                    1 if status == "ok" else 0,
                    1 if status == "fail" else 0,
                    latency_ms,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def list_source_health() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM source_health ORDER BY source")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()