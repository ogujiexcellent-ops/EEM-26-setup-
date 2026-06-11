import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                method TEXT,
                aam_current_day INTEGER DEFAULT 1,
                integration_step INTEGER DEFAULT 1,
                whatsapp_group_link TEXT,
                fb_ads_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS integration_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                whatsapp_group_link TEXT,
                step TEXT,
                status TEXT DEFAULT 'pending',
                fb_ads_details TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_user(user_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, username, first_name),
        )
        await db.commit()


async def set_user_method(user_id: int, method: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET method = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (method, user_id),
        )
        await db.commit()


async def advance_aam_day(user_id: int, day: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET aam_current_day = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (day, user_id),
        )
        await db.commit()


async def set_integration_step(user_id: int, step: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET integration_step = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (step, user_id),
        )
        await db.commit()


async def save_whatsapp_group_link(user_id: int, link: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET whatsapp_group_link = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (link, user_id),
        )
        await db.execute(
            """
            INSERT INTO integration_submissions (user_id, whatsapp_group_link, step, status)
            VALUES (?, ?, 'step1', 'pending')
            """,
            (user_id, link),
        )
        await db.commit()


async def save_fb_ads_details(user_id: int, details: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET fb_ads_details = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (details, user_id),
        )
        await db.execute(
            """
            UPDATE integration_submissions SET fb_ads_details = ?, status = 'completed'
            WHERE user_id = ? AND status = 'pending'
            """,
            (details, user_id),
        )
        await db.commit()


async def get_pending_integration_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.user_id, u.first_name, u.username, u.whatsapp_group_link, u.integration_step
            FROM users u
            WHERE u.method = 'integration' AND u.integration_step = 3
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def save_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await db.commit()


async def get_conversation_history(user_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT role, content FROM messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def clear_conversation_history(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.commit()
