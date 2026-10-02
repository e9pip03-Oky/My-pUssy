import asyncio
import aiosqlite

USER_WAITING_TASKS = {}


class UserQueueManager:
    def __init__(self, max_concurrent=2, max_queue_size=3):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self.user_semaphores = {}
        self.user_active_counts = {}

    def get_semaphore(self, user_id: int) -> asyncio.Semaphore:
        if user_id not in self.user_semaphores:
            self.user_semaphores[user_id] = asyncio.Semaphore(self.max_concurrent)
            self.user_active_counts[user_id] = 0
        return self.user_semaphores[user_id]

    def can_accept_request(self, user_id: int) -> bool:
        current_active = self.user_active_counts.get(user_id, 0)
        return current_active < (self.max_concurrent + self.max_queue_size)

    def increment_user_count(self, user_id: int):
        self.user_active_counts[user_id] = self.user_active_counts.get(user_id, 0) + 1

    def decrement_user_count(self, user_id: int):
        if user_id in self.user_active_counts:
            self.user_active_counts[user_id] -= 1
            if self.user_active_counts[user_id] <= 0:
                del self.user_active_counts[user_id]
                if user_id in self.user_semaphores:
                    del self.user_semaphores[user_id]


queue_manager = UserQueueManager(max_concurrent=2, max_queue_size=3)


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
            CREATE TABLE IF NOT EXISTS user_msg_count (
                user_id INTEGER PRIMARY KEY,
                msg_count INTEGER DEFAULT 0
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


async def should_respond_private(user_id: int) -> bool:
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute(
            "SELECT msg_count FROM user_msg_count WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            current_count = row[0] if row else 0

        new_count = current_count + 1

        if new_count >= 2:
            await db.execute(
                "INSERT OR REPLACE INTO user_msg_count (user_id, msg_count) VALUES (?, 0)",
                (user_id,)
            )
            await db.commit()
            return True
        else:
            await db.execute(
                "INSERT OR REPLACE INTO user_msg_count (user_id, msg_count) VALUES (?, ?)",
                (user_id, new_count)
            )
            await db.commit()
            return False


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


def register_user_wait_task(user_id: int, task: asyncio.Task):
    if user_id in USER_WAITING_TASKS:
        previous_task = USER_WAITING_TASKS[user_id]
        if not previous_task.done():
            previous_task.cancel()
    USER_WAITING_TASKS[user_id] = task


def clear_user_wait_task(user_id: int):
    if user_id in USER_WAITING_TASKS:
        del USER_WAITING_TASKS[user_id]
