import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path(__file__).resolve().parent / "bot_requests.db"


def init_db(db_path: Optional[Path] = None) -> Path:
    target_path = db_path or DB_PATH
    with sqlite3.connect(target_path) as connection:
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

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT '',
                field TEXT NOT NULL DEFAULT '',
                experience TEXT NOT NULL DEFAULT '',
                work_mode TEXT NOT NULL DEFAULT '',
                salary_text TEXT NOT NULL DEFAULT '',
                salary_from INTEGER,
                salary_to INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            );
            """
        )
    return target_path


def log_event(
    *,
    direction: str,
    event_type: str,
    user_id: str = "",
    chat_id: str = "",
    username: str = "",
    full_name: str = "",
    content: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    target_path = db_path or DB_PATH
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(target_path) as connection:
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


def save_user_profile(
    *,
    user_id: str,
    chat_id: str,
    city: str,
    field: str,
    experience: str,
    work_mode: str,
    salary_text: str,
    salary_from: Optional[int],
    salary_to: Optional[int],
    db_path: Optional[Path] = None,
) -> None:
    if not user_id or not chat_id:
        return

    target_path = db_path or DB_PATH
    with sqlite3.connect(target_path) as connection:
        connection.execute(
            """
            INSERT INTO user_profiles (
                user_id, chat_id, city, field, experience, work_mode, salary_text, salary_from, salary_to, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, chat_id)
            DO UPDATE SET
                city = excluded.city,
                field = excluded.field,
                experience = excluded.experience,
                work_mode = excluded.work_mode,
                salary_text = excluded.salary_text,
                salary_from = excluded.salary_from,
                salary_to = excluded.salary_to,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, chat_id, city, field, experience, work_mode, salary_text, salary_from, salary_to),
        )
        connection.commit()


def get_user_profile(
    *,
    user_id: str,
    chat_id: str,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not user_id or not chat_id:
        return {}

    target_path = db_path or DB_PATH
    with sqlite3.connect(target_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT city, field, experience, work_mode, salary_text, salary_from, salary_to, updated_at
            FROM user_profiles
            WHERE user_id = ? AND chat_id = ?
            """,
            (user_id, chat_id),
        ).fetchone()

    return dict(row) if row else {}


def fetch_recent_logs(
    *,
    user_id: str = "",
    chat_id: str = "",
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    target_path = db_path or DB_PATH
    filters = []
    params = []

    if user_id:
        filters.append("user_id = ?")
        params.append(user_id)
    if chat_id:
        filters.append("chat_id = ?")
        params.append(chat_id)

    where_clause = ""
    if filters:
        where_clause = "WHERE {0}".format(" AND ".join(filters))

    params.append(max(1, limit))
    query = """
        SELECT id, created_at, direction, event_type, content, metadata_json
        FROM request_logs
        {0}
        ORDER BY id DESC
        LIMIT ?
    """.format(where_clause)

    with sqlite3.connect(target_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, params).fetchall()

    return [dict(row) for row in rows]
