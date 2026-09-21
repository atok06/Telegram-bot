import json  # JSON форматымен жұмыс жасау үшін
import sqlite3  # SQLite деректер қорымен жұмыс жасау үшін
from pathlib import Path  # Файл жолдарымен жұмыс жасау үшін
from typing import Any, Dict, List, Optional  # Тип аннотациялары үшін


DB_PATH = Path(__file__).resolve().parent / "bot_requests.db"  # Деректер қоры файлының жолы


def init_db(db_path: Optional[Path] = None) -> Path:
    # Деректер қорын инициализациялау және кестелерді жасау
    target_path = db_path or DB_PATH  # Берілген жол немесе әдепкі жолды қолдану
    with sqlite3.connect(target_path) as connection:  # Деректер қорына қосылу
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Бірегей идентификатор, автоматты өсу
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Жазба жасалған уақыт
                direction TEXT NOT NULL,  -- Бағыт (кіріс/шығыс)
                event_type TEXT NOT NULL,  -- Оқиға түрі
                user_id TEXT,  -- Пайдаланушы ID-і
                chat_id TEXT,  -- Чат ID-і
                username TEXT,  -- Пайдаланушы аты
                full_name TEXT,  -- Пайдаланушының толық аты
                content TEXT,  -- Хабарлама мазмұны
                metadata_json TEXT  -- Қосымша деректер JSON форматында
            );

            CREATE INDEX IF NOT EXISTS idx_request_logs_created_at
            ON request_logs(created_at);  -- Уақыт бойынша жылдам іздеу индексі

            CREATE INDEX IF NOT EXISTS idx_request_logs_user_id
            ON request_logs(user_id);  -- Пайдаланушы ID бойынша жылдам іздеу индексі

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT NOT NULL,  -- Пайдаланушы ID-і
                chat_id TEXT NOT NULL,  -- Чат ID-і
                city TEXT NOT NULL DEFAULT '',  -- Қала
                field TEXT NOT NULL DEFAULT '',  -- Мамандық саласы
                experience TEXT NOT NULL DEFAULT '',  -- Тәжірибе деңгейі
                work_mode TEXT NOT NULL DEFAULT '',  -- Жұмыс форматы
                salary_text TEXT NOT NULL DEFAULT '',  -- Жалақы мәтіні
                salary_from INTEGER,  -- Жалақы минимумы
                salary_to INTEGER,  -- Жалақы максимумы
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Соңғы жаңарту уақыты
                PRIMARY KEY (user_id, chat_id)  -- Бірегей кілт: пайдаланушы + чат
            );
            """
        )
    return target_path  # Деректер қоры жолын қайтару


def log_event(
    *,
    direction: str,  # Бағыт (кіріс/шығыс)
    event_type: str,  # Оқиға түрі
    user_id: str = "",  # Пайдаланушы ID-і (міндетті емес)
    chat_id: str = "",  # Чат ID-і (міндетті емес)
    username: str = "",  # Пайдаланушы аты (міндетті емес)
    full_name: str = "",  # Толық аты (міндетті емес)
    content: str = "",  # Мазмұн (міндетті емес)
    metadata: Optional[Dict[str, Any]] = None,  # Қосымша деректер (міндетті емес)
    db_path: Optional[Path] = None,  # Деректер қоры жолы (міндетті емес)
) -> int:
    # Оқиғаны деректер қорына жазу
    target_path = db_path or DB_PATH  # Берілген жол немесе әдепкі жолды қолдану
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)  # Метадеректерді JSON-ға түрлендіру
    with sqlite3.connect(target_path) as connection:  # Деректер қорына қосылу
        cursor = connection.execute(
            """
            INSERT INTO request_logs (
                direction, event_type, user_id, chat_id, username, full_name, content, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (direction, event_type, user_id, chat_id, username, full_name, content, metadata_json),  # Мәндерді кірістіру
        )
        connection.commit()  # Өзгерістерді сақтау
        return int(cursor.lastrowid)  # Жаңа жазбаның ID-ін қайтару


def save_user_profile(
    *,
    user_id: str,  # Пайдаланушы ID-і
    chat_id: str,  # Чат ID-і
    city: str,  # Қала
    field: str,  # Мамандық саласы
    experience: str,  # Тәжірибе деңгейі
    work_mode: str,  # Жұмыс форматы
    salary_text: str,  # Жалақы мәтіні
    salary_from: Optional[int],  # Жалақы минимумы
    salary_to: Optional[int],  # Жалақы максимумы
    db_path: Optional[Path] = None,  # Деректер қоры жолы (міндетті емес)
) -> None:
    # Пайдаланушы профилін сақтау немесе жаңарту
    if not user_id or not chat_id:  # Егер ID-лер бос болса
        return  # Функциядан шығу

    target_path = db_path or DB_PATH  # Берілген жол немесе әдепкі жолды қолдану
    with sqlite3.connect(target_path) as connection:  # Деректер қорына қосылу
        connection.execute(
            """
            INSERT INTO user_profiles (
                user_id, chat_id, city, field, experience, work_mode, salary_text, salary_from, salary_to, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)  -- Жаңа жазба кірістіру
            ON CONFLICT(user_id, chat_id)  -- Егер жазба бар болса
            DO UPDATE SET  -- Барлық өрістерді жаңарту
                city = excluded.city,
                field = excluded.field,
                experience = excluded.experience,
                work_mode = excluded.work_mode,
                salary_text = excluded.salary_text,
                salary_from = excluded.salary_from,
                salary_to = excluded.salary_to,
                updated_at = CURRENT_TIMESTAMP  -- Жаңарту уақытын белгілеу
            """,
            (user_id, chat_id, city, field, experience, work_mode, salary_text, salary_from, salary_to),  # Мәндерді кірістіру
        )
        connection.commit()  # Өзгерістерді сақтау


def get_user_profile(
    *,
    user_id: str,  # Пайдаланушы ID-і
    chat_id: str,  # Чат ID-і
    db_path: Optional[Path] = None,  # Деректер қоры жолы (міндетті емес)
) -> Dict[str, Any]:
    # Пайдаланушы профилін деректер қорынан оқу
    if not user_id or not chat_id:  # Егер ID-лер бос болса
        return {}  # Бос сөздік қайтару

    target_path = db_path or DB_PATH  # Берілген жол немесе әдепкі жолды қолдану
    with sqlite3.connect(target_path) as connection:  # Деректер қорына қосылу
        connection.row_factory = sqlite3.Row  # Нәтижені сөздік ретінде алу үшін
        row = connection.execute(
            """
            SELECT city, field, experience, work_mode, salary_text, salary_from, salary_to, updated_at
            FROM user_profiles
            WHERE user_id = ? AND chat_id = ?  -- Пайдаланушы және чат бойынша іздеу
            """,
            (user_id, chat_id),  # Іздеу параметрлері
        ).fetchone()  # Бір жазбаны алу

    return dict(row) if row else {}  # Жазба бар болса сөздікке айналдырып қайтару, жоқ болса бос сөздік


def fetch_recent_logs(
    *,
    user_id: str = "",  # Пайдаланушы ID-і (міндетті емес)
    chat_id: str = "",  # Чат ID-і (міндетті емес)
    limit: int = 20,  # Максимал жазба саны (әдепкі 20)
    db_path: Optional[Path] = None,  # Деректер қоры жолы (міндетті емес)
) -> List[Dict[str, Any]]:
    # Соңғы лог жазбаларын алу
    target_path = db_path or DB_PATH  # Берілген жол немесе әдепкі жолды қолдану
    filters = []  # Фильтр шарттары тізімі
    params = []  # SQL параметрлер тізімі

    if user_id:  # Егер пайдаланушы ID берілсе
        filters.append("user_id = ?")  # Фильтр шартын қосу
        params.append(user_id)  # Параметрді қосу
    if chat_id:  # Егер чат ID берілсе
        filters.append("chat_id = ?")  # Фильтр шартын қосу
        params.append(chat_id)  # Параметрді қосу

    where_clause = ""  # WHERE шарты бастапқыда бос
    if filters:  # Егер фильтрлер бар болса
        where_clause = "WHERE {0}".format(" AND ".join(filters))  # WHERE шартын жасау

    params.append(max(1, limit))  # Лимитті параметрлер тізіміне қосу (кем дегенде 1)
    query = """
        SELECT id, created_at, direction, event_type, content, metadata_json
        FROM request_logs
        {0}
        ORDER BY id DESC  -- Соңғы жазбалар бірінші
        LIMIT ?  -- Жазба санын шектеу
    """.format(where_clause)  # WHERE шартын SQL-ге кірістіру

    with sqlite3.connect(target_path) as connection:  # Деректер қорына қосылу
        connection.row_factory = sqlite3.Row  # Нәтижені сөздік ретінде алу үшін
        rows = connection.execute(query, params).fetchall()  # Барлық жазбаларды алу

    return [dict(row) for row in rows]  # Жазбаларды сөздіктер тізіміне айналдырып қайтару