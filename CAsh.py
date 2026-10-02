import aiosqlite


async def init_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS cached_files (
                media_key TEXT,
                mode TEXT,
                file_id TEXT,
                PRIMARY KEY (media_key, mode)
            )
            """
        )
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
                last_index INTEGER DEFAULT -1
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_logs (
                message_id INTEGER,
                chat_id INTEGER,
                user_id INTEGER,
                file_id TEXT,
                is_bot BOOLEAN,
                PRIMARY KEY (message_id, chat_id)
            )
            """
        )
        await db.commit()


async def add_user(user_id: int):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )
        await db.commit()


async def get_cached_file(media_key: str, mode: str) -> str:
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute(
            "SELECT file_id FROM cached_files WHERE media_key = ? AND mode = ?",
            (media_key, mode)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def save_cached_file(media_key: str, mode: str, file_id: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO cached_files (media_key, mode, file_id) VALUES (?, ?, ?)",
            (media_key, mode, file_id)
        )
        await db.commit()


async def set_chat_mode(chat_id: int, thread_id: int, mode: str):
    target_thread_id = thread_id if thread_id is not None else 0
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO chat_modes (chat_id, thread_id, mode) VALUES (?, ?, ?)",
            (chat_id, target_thread_id, mode)
        )
        await db.commit()


async def get_chat_mode(chat_id: int, thread_id: int) -> str:
    target_thread_id = thread_id if thread_id is not None else 0
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute(
            "SELECT mode FROM chat_modes WHERE chat_id = ? AND thread_id = ?",
            (chat_id, target_thread_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "normal"


async def get_next_rotating_response(user_id: int, responses_list: list) -> str:
    if not responses_list:
        return ""

    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute(
            "SELECT last_index FROM user_rotation WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            last_index = row[0] if row else -1

        next_index = (last_index + 1) % len(responses_list)

        await db.execute(
            "INSERT OR REPLACE INTO user_rotation (user_id, last_index) VALUES (?, ?)",
            (user_id, next_index)
        )
        await db.commit()

        return responses_list[next_index]


async def save_voice_log(message_id: int, chat_id: int, user_id: int, file_id: str, is_bot: bool):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO voice_logs (message_id, chat_id, user_id, file_id, is_bot) VALUES (?, ?, ?, ?, ?)",
            (message_id, chat_id, user_id, file_id, is_bot)
        )
        await db.commit()


async def get_voice_log(message_id: int, chat_id: int) -> str:
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute(
            "SELECT file_id FROM voice_logs WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
