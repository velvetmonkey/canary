"""SQLite document state store for change detection."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = """\
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
"""


class DocumentStore:
    """Wraps SQLite for document state and change history."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)

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
