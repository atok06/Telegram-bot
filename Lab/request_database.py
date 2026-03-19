import json
import sqlite3
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parent / "bot_requests.db"


def init_db(db_path: Path | None = None) -> Path:
    db_path = db_path or DB_PATH
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                direction TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT,
                chat_id TEXT,
                username TEXT,
                full_name TEXT,
                content TEXT,
                metadata_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_request_logs_created_at
            ON request_logs(created_at);

            CREATE INDEX IF NOT EXISTS idx_request_logs_user_id
            ON request_logs(user_id);
            """
        )
    return db_path


def log_event(
    *,
    direction: str,
    event_type: str,
    user_id: str = "",
    chat_id: str = "",
    username: str = "",
    full_name: str = "",
    content: str = "",
    metadata: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> int:
    db_path = db_path or DB_PATH
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO request_logs (
                direction, event_type, user_id, chat_id, username, full_name, content, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (direction, event_type, user_id, chat_id, username, full_name, content, metadata_json),
        )
        connection.commit()
        return int(cursor.lastrowid)
