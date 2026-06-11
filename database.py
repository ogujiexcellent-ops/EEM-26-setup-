from datetime import datetime, timezone
import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                user_id        INTEGER PRIMARY KEY,
                username       TEXT,
                first_name     TEXT,
                current_lesson INTEGER DEFAULT 1,
                last_accessed  TEXT,
                enrolled_at    TEXT DEFAULT (datetime('now')),
                is_active      INTEGER DEFAULT 1
            )
        """)
        await db.commit()


async def get_student(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM students WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def enroll_student(user_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO students (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                is_active  = 1
            """,
            (user_id, username or "", first_name or ""),
        )
        await db.commit()


async def record_lesson_access(user_id: int, lesson_number: int):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE students
            SET current_lesson = ?,
                last_accessed  = ?
            WHERE user_id = ?
            """,
            (lesson_number, now, user_id),
        )
        await db.commit()


async def get_all_students() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM students ORDER BY enrolled_at"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def reset_student_progress(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE students SET current_lesson = 1, last_accessed = NULL WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def set_student_active(user_id: int, active: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE students SET is_active = ? WHERE user_id = ?",
            (1 if active else 0, user_id),
        )
        await db.commit()
