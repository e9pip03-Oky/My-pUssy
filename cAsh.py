import asyncio
import collections
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Final

import redis.asyncio as aioredis
from aiogram.types import Message

log = logging.getLogger("voicebot")

MAX_CONCURRENT: Final = 3
MAX_WAITING: Final = 18
BASE_DIR: Final = "downloads"
CACHE_PREFIX: Final = "voice:"
PENDING_TTL: Final = 6 * 60 * 60

ffmpeg_semaphore: Final = asyncio.Semaphore(1)


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


@dataclass(frozen=True)
class ModeContext:
    chat_id: int
    user_id: int
    mode_key: str


def get_mode_context(message: Message) -> ModeContext:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    thread_id = message.message_thread_id
    mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)
    return ModeContext(chat_id, user_id, mode_key)


def get_mode_key(message: Message) -> str:
    return get_mode_context(message).mode_key


class ChatQueue:
    def __init__(self) -> None:
        self._slots: dict[int, int] = {}
        self._waiters: dict[int, collections.deque[asyncio.Future]] = {}
        self._meta_lock = asyncio.Lock()

    async def _ensure(self, chat_id: int) -> None:
        async with self._meta_lock:
            if chat_id not in self._slots:
                self._slots[chat_id] = MAX_CONCURRENT
                self._waiters[chat_id] = collections.deque()

    async def _handoff(self, chat_id: int) -> None:
        waiters = self._waiters[chat_id]
        if waiters:
            fut = waiters.popleft()
            if not fut.done():
                fut.set_result(True)
        elif self._slots[chat_id] < MAX_CONCURRENT:
            self._slots[chat_id] += 1

    async def acquire(self, chat_id: int) -> tuple[bool, bool]:
        await self._ensure(chat_id)
        async with self._meta_lock:
            if self._slots[chat_id] > 0 and not self._waiters[chat_id]:
                self._slots[chat_id] -= 1
                return True, False
            if len(self._waiters[chat_id]) >= MAX_WAITING:
                return False, False
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters[chat_id].append(fut)
        try:
            await fut
        except BaseException:
            async with self._meta_lock:
                try:
                    self._waiters[chat_id].remove(fut)
                except ValueError:
                    if fut.done() and not fut.cancelled():
                        await self._handoff(chat_id)
            raise
        return True, True

    async def release(self, chat_id: int) -> None:
        await self._ensure(chat_id)
        async with self._meta_lock:
            await self._handoff(chat_id)


class FileLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def get(self, key: str) -> asyncio.Lock:
        async with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]


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


class NotifStorage(RedisBase):
    async def get(self, mode_key: str) -> bool:
        return await self._get(CACHE_PREFIX + f"notif:{mode_key}") == "1"

    async def set(self, mode_key: str, active: bool) -> None:
        await self._set(CACHE_PREFIX + f"notif:{mode_key}", _ser_bool(active))


class AllowedStorage(RedisBase):
    async def get(self, user_id: int) -> bool | None:
        value = await self._get(CACHE_PREFIX + f"allowed:{user_id}")
        if value is None:
            return None
        return value == "1"

    async def set(self, user_id: int, allowed: bool) -> None:
        await self._set(CACHE_PREFIX + f"allowed:{user_id}", _ser_bool(allowed))


class PendingStorage(RedisBase):
    async def get(self, user_id: int) -> bool:
        return await self._get(CACHE_PREFIX + f"pending:{user_id}") == "1"

    async def set(self, user_id: int, pending: bool) -> None:
        key = CACHE_PREFIX + f"pending:{user_id}"
        if pending:
            await self._set(key, "1", ttl=PENDING_TTL)
        else:
            await self._del(key)


def _root(chat_id: int, bot_id: int, is_private: bool) -> str:
    return str(bot_id) if is_private else str(chat_id).removeprefix("-")


def user_dir(chat_id: int, user_id: int, bot_id: int, is_private: bool) -> str:
    path = os.path.join(BASE_DIR, _root(chat_id, bot_id, is_private), str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def prune_downloads() -> None:
    if not os.path.isdir(BASE_DIR):
        return
    for root, dirs, files in os.walk(BASE_DIR, topdown=False):
        if root == BASE_DIR:
            continue
        if not dirs and not files:
            try:
                os.rmdir(root)
            except OSError:
                pass


def cleanup(
    chat_id: int,
    user_id: int,
    bot_id: int,
    is_private: bool,
    *prefixes: str | int,
) -> None:
    root = _root(chat_id, bot_id, is_private)
    user_path = os.path.join(BASE_DIR, root, str(user_id))
    if os.path.isdir(user_path):
        valid = tuple(str(prefix) for prefix in prefixes if prefix)
        if valid:
            for filename in os.listdir(user_path):
                if any(
                    filename == prefix
                    or filename.startswith(prefix + ".")
                    or filename.startswith(prefix + "_")
                    for prefix in valid
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
    prune_downloads()


queue: Final = ChatQueue()
file_locks: Final = FileLockRegistry()
