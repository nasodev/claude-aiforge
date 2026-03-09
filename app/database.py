import aiosqlite
import json
import os
from pathlib import Path

DB_PATH = os.environ.get("AIFORGE_DB", "aiforge.db")
SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """스키마 생성 + 기본 설정 삽입"""
    db = await get_db()
    try:
        schema_sql = SCHEMA_PATH.read_text()
        await db.executescript(schema_sql)

        # 기본 설정이 없으면 삽입 (config = 사용자 설정, status = 실시간 상태)
        default_settings = {
            # 토큰 체크 - 설정
            "token_check_config": {
                "enabled": True,
                "interval_minutes": 60,
                "session_limit_percent": 60,
                "weekly_limit_percent": 80,
            },
            # 토큰 체크 - 상태 (claude CLI 실행 결과가 여기 저장됨)
            "token_check_status": {
                "current_session_percent": 0,
                "weekly_limit_percent": 0,
                "last_checked": None,
                "error": None,
                "raw_response": None,
            },
            # 로그 모니터 - 설정
            "log_monitor_config": {
                "enabled": True,
                "interval_minutes": 10,
            },
            # 로그 모니터 - 상태
            "log_monitor_status": {
                "last_checked": None,
            },
            # 글로벌 설정
            "global": {
                "auto_pause_on_limit": True,
                "max_concurrent_executions": 3,
            },
        }

        for key, value in default_settings.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

        await db.commit()
    finally:
        await db.close()


async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def fetch_one(query: str, params: tuple = ()) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def execute(query: str, params: tuple = ()):
    db = await get_db()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()


async def get_setting(key: str) -> dict | None:
    row = await fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
    if row:
        return json.loads(row["value"])
    return None


async def update_setting(key: str, value: dict):
    await execute(
        "UPDATE settings SET value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') WHERE key = ?",
        (json.dumps(value), key),
    )
