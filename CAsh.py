import aiosqlite


async def init_db():
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_modes (
                chat_id INTEGER,
                thread_id INTEGER,
                mode TEXT DEFAULT 'normal',
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_rotation (
                user_id INTEGER PRIMARY KEY,
                last_index INTEGER DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                item_id TEXT,
                mode TEXT,
                file_id TEXT,
                PRIMARY KEY (item_id, mode)
            )
            """
        )
        await db.commit()


async def get_chat_mode(chat_id: int, thread_id: int) -> str:
    tid = thread_id if thread_id is not None else 0
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute(
            "SELECT mode FROM chat_modes WHERE chat_id = ? AND thread_id = ?",
            (chat_id, tid),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return "normal"


async def toggle_chat_mode(chat_id: int, thread_id: int) -> str:
    tid = thread_id if thread_id is not None else 0
    current_mode = await get_chat_mode(chat_id, tid)
    new_mode = "voice" if current_mode == "normal" else "normal"
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute(
            """
            INSERT INTO chat_modes (chat_id, thread_id, mode)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, thread_id) DO UPDATE SET mode = excluded.mode
            """,
            (chat_id, tid, new_mode),
        )
        await db.commit()
    return new_mode


async def get_next_user_index(user_id: int, total_items: int) -> int:
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute(
            "SELECT last_index FROM user_rotation WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            current_index = row[0] if row else 0

        next_index = (current_index + 1) % total_items
        await db.execute(
            """
            INSERT INTO user_rotation (user_id, last_index)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_index = excluded.last_index
            """,
            (user_id, next_index),
        )
        await db.commit()
        return current_index


async def get_cached_file_id(item_id: str, mode: str):
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute(
            "SELECT file_id FROM file_cache WHERE item_id = ? AND mode = ?",
            (item_id, mode),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def save_cached_file_id(item_id: str, mode: str, file_id: str):
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute(
            """
            INSERT INTO file_cache (item_id, mode, file_id)
            VALUES (?, ?, ?)
            ON CONFLICT(item_id, mode) DO UPDATE SET file_id = excluded.file_id
            """,
            (item_id, mode, file_id),
        )
        await db.commit()
