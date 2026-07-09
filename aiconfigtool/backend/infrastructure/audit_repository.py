"""操作记录仓库（SQLite，stdlib sqlite3，零安装依赖）。

严格按技术设计文档 13.1 建表：sessions + operations + 索引。
每个 API 请求/后台操作都通过此仓库记录，用于回答"谁在什么时候做了什么"。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from typing import Optional


def _default_db_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "..", "data", "audit.db")


class AuditRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        path = os.path.abspath(db_path or _default_db_path())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    session_id  TEXT NOT NULL,
                    op_type     TEXT NOT NULL,
                    site_code   TEXT,
                    company_code TEXT,
                    params_json TEXT,
                    result      TEXT NOT NULL,
                    run_id      TEXT,
                    error_code  TEXT,
                    duration_ms INTEGER,
                    addon_hash  TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    last_active TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                    notes       TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ops_ts ON operations(ts);
                CREATE INDEX IF NOT EXISTS idx_ops_type ON operations(op_type);
                CREATE INDEX IF NOT EXISTS idx_ops_site ON operations(site_code);
            """)

    # ── 会话 ──
    def start_session(self, notes: str = "") -> str:
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, notes) VALUES (?, ?)", (sid, notes)
            )
            self._conn.commit()
        return sid

    def touch_session(self, session_id: str):
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET last_active = datetime('now','localtime') WHERE id = ?",
                (session_id,),
            )
            self._conn.commit()

    # ── 操作记录 ──
    def log_operation(
        self,
        session_id: str,
        op_type: str,
        site_code: str | None = None,
        company_code: str | None = None,
        params: dict | None = None,
        result: str = "success",
        run_id: str | None = None,
        error_code: str | None = None,
        duration_ms: int | None = None,
        addon_hash: str | None = None,
    ) -> int:
        params_json = json.dumps(params, ensure_ascii=False) if params else None
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO operations
                   (session_id, op_type, site_code, company_code, params_json,
                    result, run_id, error_code, duration_ms, addon_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, op_type, site_code, company_code, params_json,
                    result, run_id, error_code, duration_ms, addon_hash,
                ),
            )
            self._conn.commit()
        self.touch_session(session_id)
        return cur.lastrowid

    # ── 查询 ──
    def query(
        self,
        op_type: str | None = None,
        site_code: str | None = None,
        since: str | None = None,
        result: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses = []
        args: list = []
        if op_type:
            clauses.append("op_type = ?"); args.append(op_type)
        if site_code:
            clauses.append("site_code = ?"); args.append(site_code)
        if since:
            clauses.append("ts >= ?"); args.append(since)
        if result:
            clauses.append("result = ?"); args.append(result)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM operations{where} ORDER BY ts DESC LIMIT ?",
                args + [limit],
            ).fetchall()
        cols = [
            "id", "ts", "session_id", "op_type", "site_code", "company_code",
            "params_json", "result", "run_id", "error_code", "duration_ms", "addon_hash",
        ]
        return [dict(zip(cols, r)) for r in rows]
