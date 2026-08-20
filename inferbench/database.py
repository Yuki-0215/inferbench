from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import SampleRecord


class Repository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def init(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    framework TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    completed_requests INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    request_index INTEGER NOT NULL,
                    ok INTEGER NOT NULL,
                    status_code INTEGER,
                    latency_ms REAL NOT NULL,
                    ttft_ms REAL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    token_source TEXT NOT NULL,
                    error TEXT,
                    started_offset_ms REAL NOT NULL,
                    UNIQUE(run_id, request_index)
                );
                CREATE INDEX IF NOT EXISTS idx_samples_run_id ON samples(run_id);
                """
            )

    def recover_interrupted_runs(self) -> int:
        """Close runs orphaned when the local process exited unexpectedly."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE runs
                SET status='cancelled', finished_at=?,
                    error=COALESCE(error, 'local runner restarted before completion')
                WHERE status IN ('queued', 'running')""",
                (time.time(),),
            )
        return cursor.rowcount

    def create_run(
        self,
        run_id: str,
        name: str,
        framework: str,
        endpoint: str,
        model: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO runs
                (id, name, status, framework, endpoint, model, config_json, created_at)
                VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (run_id, name, framework, endpoint, model, json.dumps(config), now),
            )
        return self.get_run(run_id)

    def set_running(self, run_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status='running', started_at=?, error=NULL WHERE id=?",
                (time.time(), run_id),
            )

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status=?, finished_at=?, error=? WHERE id=?",
                (status, time.time(), error, run_id),
            )

    def add_sample(self, run_id: str, sample: SampleRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO samples
                (run_id, request_index, ok, status_code, latency_ms, ttft_ms,
                 input_tokens, output_tokens, token_source, error, started_offset_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    sample.request_index,
                    int(sample.ok),
                    sample.status_code,
                    sample.latency_ms,
                    sample.ttft_ms,
                    sample.input_tokens,
                    sample.output_tokens,
                    sample.token_source,
                    sample.error,
                    sample.started_offset_ms,
                ),
            )
            connection.execute(
                "UPDATE runs SET completed_requests = completed_requests + 1 WHERE id=?",
                (run_id,),
            )

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        return item

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                   OR id IN (
                       SELECT id FROM runs
                       WHERE status NOT IN ('queued', 'running')
                       ORDER BY created_at DESC LIMIT ?
                   )
                ORDER BY created_at DESC""",
                (limit,),
            ).fetchall()
        return [self._run_dict(row) for row in rows]

    def list_samples(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM samples WHERE run_id=? ORDER BY request_index", (run_id,)
            ).fetchall()
        return [dict(row) | {"ok": bool(row["ok"])} for row in rows]

    def delete_run(self, run_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM runs WHERE id=?", (run_id,))
        return cursor.rowcount > 0
