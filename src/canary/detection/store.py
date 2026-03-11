"""SQLite document state store for change detection."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from canary.tracing import RunMetrics

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS document_state (
    celex_id TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    text TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    last_changed TEXT
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    celex_id TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    old_hash TEXT,
    new_hash TEXT NOT NULL,
    diff_summary TEXT,
    materiality TEXT,
    canary_run_id TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms REAL,
    sources_checked INTEGER DEFAULT 0,
    changes_detected INTEGER DEFAULT 0,
    baselines_stored INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    extraction_tokens_in INTEGER DEFAULT 0,
    extraction_tokens_out INTEGER DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS source_check_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    celex_id TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    duration_ms REAL,
    hash TEXT,
    change_count INTEGER DEFAULT 0,
    citations_total INTEGER DEFAULT 0,
    citations_verified INTEGER DEFAULT 0,
    vault_path TEXT,
    error TEXT,
    FOREIGN KEY (run_id) REFERENCES run_log(run_id)
);

CREATE INDEX IF NOT EXISTS idx_change_log_celex ON change_log(celex_id);
CREATE INDEX IF NOT EXISTS idx_source_check_run ON source_check_log(run_id);
CREATE INDEX IF NOT EXISTS idx_run_log_started ON run_log(started_at);
"""


class DocumentStore:
    """Wraps SQLite for document state and change history."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._check_schema_version()

    def _check_schema_version(self) -> None:
        """Ensure schema version matches. Initialize if empty, fail if mismatched."""
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self.conn.commit()
        elif row["version"] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version mismatch: expected {SCHEMA_VERSION}, "
                f"got {row['version']}. Migrate or recreate the database."
            )

    def prune(self, days: int = 90) -> dict[str, int]:
        """Delete run_log and source_check_log entries older than N days. Returns counts."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Find old run IDs first
        old_runs = self.conn.execute(
            "SELECT run_id FROM run_log WHERE started_at < ?", (cutoff,)
        ).fetchall()
        old_run_ids = [r["run_id"] for r in old_runs]

        source_checks_deleted = 0
        if old_run_ids:
            placeholders = ",".join("?" * len(old_run_ids))
            cur = self.conn.execute(
                f"DELETE FROM source_check_log WHERE run_id IN ({placeholders})",
                old_run_ids,
            )
            source_checks_deleted = cur.rowcount

        cur = self.conn.execute("DELETE FROM run_log WHERE started_at < ?", (cutoff,))
        runs_deleted = cur.rowcount

        self.conn.commit()
        self.conn.execute("VACUUM")

        logger.info(
            "Pruned %d runs and %d source checks older than %d days",
            runs_deleted, source_checks_deleted, days,
        )
        return {"runs_deleted": runs_deleted, "source_checks_deleted": source_checks_deleted}

    def close(self) -> None:
        self.conn.close()

    def get_state(self, celex_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM document_state WHERE celex_id = ?", (celex_id,)
        ).fetchone()

    def upsert_state(self, celex_id: str, hash_val: str, text: str) -> bool:
        """Insert or update document state. Returns True if this was a change (or first insert)."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_state(celex_id)

        if existing is None:
            self.conn.execute(
                "INSERT INTO document_state (celex_id, hash, text, last_checked, last_changed) "
                "VALUES (?, ?, ?, ?, ?)",
                (celex_id, hash_val, text, now, now),
            )
            self.conn.commit()
            return True

        if existing["hash"] != hash_val:
            self.conn.execute(
                "UPDATE document_state SET hash = ?, text = ?, last_checked = ?, last_changed = ? "
                "WHERE celex_id = ?",
                (hash_val, text, now, now, celex_id),
            )
            self.conn.commit()
            return True

        # No change — just update last_checked
        self.conn.execute(
            "UPDATE document_state SET last_checked = ? WHERE celex_id = ?",
            (now, celex_id),
        )
        self.conn.commit()
        return False

    def log_change(
        self,
        celex_id: str,
        old_hash: str | None,
        new_hash: str,
        diff_summary: str | None = None,
        materiality: str | None = None,
        run_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO change_log (celex_id, detected_at, old_hash, new_hash, diff_summary, "
            "materiality, canary_run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (celex_id, now, old_hash, new_hash, diff_summary, materiality, run_id),
        )
        self.conn.commit()

    def get_change_log(self, celex_id: str | None = None) -> list[sqlite3.Row]:
        if celex_id:
            return self.conn.execute(
                "SELECT * FROM change_log WHERE celex_id = ? ORDER BY detected_at DESC",
                (celex_id,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM change_log ORDER BY detected_at DESC"
        ).fetchall()

    # --- Run logging ---

    def save_run(self, metrics: "RunMetrics") -> None:
        """Persist a complete run and its source checks."""
        import json

        self.conn.execute(
            "INSERT OR REPLACE INTO run_log "
            "(run_id, started_at, completed_at, duration_ms, sources_checked, "
            "changes_detected, baselines_stored, errors, extraction_tokens_in, "
            "extraction_tokens_out, summary_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metrics.run_id,
                metrics.started_at,
                metrics.completed_at,
                metrics.duration_ms,
                metrics.sources_checked,
                metrics.changes_detected,
                metrics.baselines_stored,
                metrics.errors,
                metrics.extraction_tokens_in,
                metrics.extraction_tokens_out,
                json.dumps(metrics.summary()),
            ),
        )

        for sc in metrics.source_checks:
            self.conn.execute(
                "INSERT INTO source_check_log "
                "(run_id, celex_id, label, status, started_at, duration_ms, hash, "
                "change_count, citations_total, citations_verified, vault_path, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    metrics.run_id,
                    sc.celex_id,
                    sc.label,
                    sc.status,
                    datetime.now(timezone.utc).isoformat(),
                    sc.duration_ms,
                    sc.hash,
                    sc.change_count,
                    sc.citations_total,
                    sc.citations_verified,
                    sc.vault_path,
                    sc.error,
                ),
            )

        self.conn.commit()

    def get_run_log(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def get_source_checks(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM source_check_log WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
