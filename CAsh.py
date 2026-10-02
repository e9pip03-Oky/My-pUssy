import asyncio
import sqlite3


USER_WAITING_TASKS = {}


class UserQueueManager:
    def __init__(
        self,
        max_concurrent=2,
        max_queue_size=3,
    ):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self.user_semaphores = {}
        self.user_active_counts = {}

    def get_semaphore(
        self,
        user_id: int,
    ) -> asyncio.Semaphore:
        if user_id not in self.user_semaphores:
            self.user_semaphores[user_id] = asyncio.Semaphore(
                self.max_concurrent
            )
            self.user_active_counts[user_id] = 0

        return self.user_semaphores[user_id]

    def can_accept_request(
        self,
        user_id: int,
    ) -> bool:
        current_active = self.user_active_counts.get(
            user_id,
            0,
        )

        return current_active < (
            self.max_concurrent + self.max_queue_size
        )

    def increment_user_count(self, user_id: int):
        self.user_active_counts[user_id] = (
            self.user_active_counts.get(user_id, 0) + 1
        )

    def decrement_user_count(self, user_id: int):
        if user_id not in self.user_active_counts:
            return

        self.user_active_counts[user_id] -= 1

        if self.user_active_counts[user_id] <= 0:
            del self.user_active_counts[user_id]

            if user_id in self.user_semaphores:
                del self.user_semaphores[user_id]


queue_manager = UserQueueManager(
    max_concurrent=2,
    max_queue_size=3,
)


def _sync_init_db():
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cached_files (
                media_key TEXT,
                mode TEXT,
                file_id TEXT,
                PRIMARY KEY (media_key, mode)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_modes (
                chat_id INTEGER,
                thread_id INTEGER,
                mode TEXT DEFAULT 'normal',
                PRIMARY KEY (chat_id, thread_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_rotation (
                user_id INTEGER PRIMARY KEY,
                last_index INTEGER DEFAULT -1
            )
            """
        )

        conn.commit()


async def init_db():
    await asyncio.to_thread(_sync_init_db)


def _sync_add_user(user_id: int):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )

        conn.commit()


async def add_user(user_id: int):
    await asyncio.to_thread(
        _sync_add_user,
        user_id,
    )


def _sync_get_cached_file(
    media_key: str,
    mode: str,
) -> str:
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT file_id
            FROM cached_files
            WHERE media_key = ? AND mode = ?
            """,
            (media_key, mode),
        )

        row = cursor.fetchone()

        return row[0] if row else None


async def get_cached_file(
    media_key: str,
    mode: str,
) -> str:
    return await asyncio.to_thread(
        _sync_get_cached_file,
        media_key,
        mode,
    )


def _sync_save_cached_file(
    media_key: str,
    mode: str,
    file_id: str,
):
    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO cached_files
            (media_key, mode, file_id)
            VALUES (?, ?, ?)
            """,
            (media_key, mode, file_id),
        )

        conn.commit()


async def save_cached_file(
    media_key: str,
    mode: str,
    file_id: str,
):
    await asyncio.to_thread(
        _sync_save_cached_file,
        media_key,
        mode,
        file_id,
    )


def _sync_set_chat_mode(
    chat_id: int,
    thread_id: int,
    mode: str,
):
    target_thread_id = (
        thread_id
        if thread_id is not None
        else 0
    )

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO chat_modes
            (chat_id, thread_id, mode)
            VALUES (?, ?, ?)
            """,
            (
                chat_id,
                target_thread_id,
                mode,
            ),
        )

        conn.commit()


async def set_chat_mode(
    chat_id: int,
    thread_id: int,
    mode: str,
):
    await asyncio.to_thread(
        _sync_set_chat_mode,
        chat_id,
        thread_id,
        mode,
    )


def _sync_get_chat_mode(
    chat_id: int,
    thread_id: int,
) -> str:
    target_thread_id = (
        thread_id
        if thread_id is not None
        else 0
    )

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT mode
            FROM chat_modes
            WHERE chat_id = ? AND thread_id = ?
            """,
            (
                chat_id,
                target_thread_id,
            ),
        )

        row = cursor.fetchone()

        return row[0] if row else "normal"


async def get_chat_mode(
    chat_id: int,
    thread_id: int,
) -> str:
    return await asyncio.to_thread(
        _sync_get_chat_mode,
        chat_id,
        thread_id,
    )


def _sync_get_next_rotating_response(
    user_id: int,
    responses_list: list,
) -> str:
    if not responses_list:
        return ""

    with sqlite3.connect("bot_data.db") as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT last_index
            FROM user_rotation
            WHERE user_id = ?
            """,
            (user_id,),
        )

        row = cursor.fetchone()
        last_index = row[0] if row else -1

        next_index = (
            last_index + 1
        ) % len(responses_list)

        cursor.execute(
            """
            INSERT OR REPLACE INTO user_rotation
            (user_id, last_index)
            VALUES (?, ?)
            """,
            (
                user_id,
                next_index,
            ),
        )

        conn.commit()

        return responses_list[next_index]


async def get_next_rotating_response(
    user_id: int,
    responses_list: list,
) -> str:
    return await asyncio.to_thread(
        _sync_get_next_rotating_response,
        user_id,
        responses_list,
    )


def register_user_wait_task(
    user_id: int,
    task: asyncio.Task,
):
    previous_task = USER_WAITING_TASKS.get(user_id)

    if previous_task and not previous_task.done():
        previous_task.cancel()

    USER_WAITING_TASKS[user_id] = task


def clear_user_wait_task(user_id: int):
    USER_WAITING_TASKS.pop(
        user_id,
        None,
    )