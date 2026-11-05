import asyncio
import hashlib
import logging
import os

import redis.asyncio as aioredis
from aiogram.types import Message

log = logging.getLogger("voicebot")

MAX_CONCURRENT = 3
MAX_WAITING = 18
BASE_DIR = "downloads"
CACHE_PREFIX = "voice:"
FILE_ID_TTL = 60 * 60 * 24 * 30

ffmpeg_semaphore = asyncio.Semaphore(1)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parse_bool(parts: list[str], index: int) -> bool:
    return len(parts) > index and parts[index] == "1"


def _ser_bool(value) -> str:
    return "1" if value else "0"


async def safe_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


def get_mode_key(message: Message) -> tuple[int, int, str]:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    thread_id = message.message_thread_id
    mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)
    return chat_id, user_id, mode_key


class ChatQueue:
    def __init__(self) -> None:
        self._slots: dict[int, asyncio.Queue[None]] = {}
        self._waiting: dict[int, int] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def _lock(self, chat_id: int) -> asyncio.Lock:
        async with self._meta_lock:
            if chat_id not in self._locks:
                self._locks[chat_id] = asyncio.Lock()
            return self._locks[chat_id]

    async def _queue(self, chat_id: int) -> asyncio.Queue[None]:
        async with self._meta_lock:
            if chat_id not in self._slots:
                queue: asyncio.Queue[None] = asyncio.Queue()
                for _ in range(MAX_CONCURRENT):
                    queue.put_nowait(None)
                self._slots[chat_id] = queue
            return self._slots[chat_id]

    async def acquire(self, chat_id: int) -> tuple[bool, bool]:
        lock = await self._lock(chat_id)
        queue = await self._queue(chat_id)
        async with lock:
            if not queue.empty():
                queue.get_nowait()
                return True, False
            if self._waiting.get(chat_id, 0) >= MAX_WAITING:
                return False, False
            self._waiting[chat_id] = self._waiting.get(chat_id, 0) + 1
        try:
            await queue.get()
        except asyncio.CancelledError:
            async with lock:
                self._waiting[chat_id] = max(0, self._waiting[chat_id] - 1)
            raise
        async with lock:
            self._waiting[chat_id] = max(0, self._waiting[chat_id] - 1)
        return True, True

    async def release(self, chat_id: int) -> None:
        queue = await self._queue(chat_id)
        queue.put_nowait(None)


class RedisBase:
    def __init__(self, client: aioredis.Redis | None) -> None:
        self._client = client
        self._memory: dict[str, str] = {}

    async def _get(self, key: str) -> str | None:
        if self._client:
            value = await self._client.get(key)
            return value.decode() if value else None
        return self._memory.get(key)

    async def _set(self, key: str, value: str, ttl: int | None = None) -> None:
        if self._client:
            if ttl:
                await self._client.set(key, value, ex=ttl)
            else:
                await self._client.set(key, value)
        else:
            self._memory[key] = value

    async def _del(self, key: str) -> None:
        if self._client:
            await self._client.delete(key)
        else:
            self._memory.pop(key, None)


class ModeStorage(RedisBase):
    async def get(self, mode_key: str) -> str:
        return await self._get(CACHE_PREFIX + f"mode:{mode_key}") or "voice"

    async def set(self, mode_key: str, mode: str) -> None:
        await self._set(CACHE_PREFIX + f"mode:{mode_key}", mode)

    async def get_previous(self, mode_key: str) -> str:
        return await self._get(CACHE_PREFIX + f"prev_mode:{mode_key}") or "voice"

    async def set_previous(self, mode_key: str, mode: str) -> None:
        await self._set(CACHE_PREFIX + f"prev_mode:{mode_key}", mode)


class LangStorage(RedisBase):
    async def get(self, mode_key: str) -> bool:
        return await self._get(CACHE_PREFIX + f"lang:{mode_key}") == "1"

    async def set(self, mode_key: str, active: bool) -> None:
        await self._set(CACHE_PREFIX + f"lang:{mode_key}", _ser_bool(active))


class LangCodeStorage(RedisBase):
    async def get(self, mode_key: str) -> str:
        return await self._get(CACHE_PREFIX + f"lang_code:{mode_key}") or "en"

    async def set(self, mode_key: str, code: str) -> None:
        await self._set(CACHE_PREFIX + f"lang_code:{mode_key}", code)


class ReplyCounter(RedisBase):
    async def next_index(self, user_id: int, size: int) -> int:
        key = CACHE_PREFIX + f"reply:{user_id}"
        value = await self._get(key)
        index = int(value) if value else 0
        await self._set(key, str((index + 1) % size))
        return index


class AdtStorage(RedisBase):
    async def get_messages(self, mode_key: str) -> list[int]:
        value = await self._get(CACHE_PREFIX + f"adt:{mode_key}")
        return [int(item) for item in value.split(",") if item] if value else []

    async def save_messages(self, mode_key: str, message_ids: list[int]) -> None:
        await self._set(
            CACHE_PREFIX + f"adt:{mode_key}", ",".join(map(str, message_ids))
        )


class ButtonCycleStorage(RedisBase):
    async def get_index(self, chat_id: int) -> int:
        value = await self._get(CACHE_PREFIX + f"btn_cycle:{chat_id}")
        return int(value) if value else 0

    async def advance(self, chat_id: int, total: int) -> None:
        index = await self.get_index(chat_id)
        await self._set(CACHE_PREFIX + f"btn_cycle:{chat_id}", str((index + 1) % total))


def _root(chat_id: int, bot_id: int, is_private: bool) -> str:
    return str(bot_id) if is_private else str(chat_id).removeprefix("-")


def user_dir(chat_id: int, user_id: int, bot_id: int, is_private: bool) -> str:
    path = os.path.join(BASE_DIR, _root(chat_id, bot_id, is_private), str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def cleanup(
    chat_id: int, user_id: int, bot_id: int, is_private: bool, *message_ids: int
) -> None:
    root = _root(chat_id, bot_id, is_private)
    user_path = os.path.join(BASE_DIR, root, str(user_id))
    if os.path.isdir(user_path):
        prefixes = tuple(str(mid) for mid in message_ids if mid)
        if prefixes:
            for filename in os.listdir(user_path):
                if any(
                    filename == prefix
                    or filename.startswith(prefix + ".")
                    or filename.startswith(prefix + "_")
                    for prefix in prefixes
                ):
                    try:
                        os.remove(os.path.join(user_path, filename))
                    except OSError:
                        pass
    for path in (user_path, os.path.join(BASE_DIR, root)):
        try:
            os.rmdir(path)
        except OSError:
            pass


queue = ChatQueue()