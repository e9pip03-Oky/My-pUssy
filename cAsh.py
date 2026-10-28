import asyncio
import hashlib
import logging
import os

import redis.asyncio as aioredis
from aiogram.fsm.storage.redis import RedisStorage

log = logging.getLogger("voicebot")
MAX_CONCURRENT = 3
MAX_WAITING = 3
BASE_DIR = "downloads"
CACHE_PREFIX = "voice:"
FILE_ID_TTL = 60 * 60 * 24 * 30


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ChatQueue:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._running: dict[int, int] = {}
        self._waiting: dict[int, int] = {}
        self._events: dict[int, list[asyncio.Event]] = {}

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def acquire(self, chat_id: int) -> tuple[bool, asyncio.Event | None]:
        async with self._lock(chat_id):
            running = self._running.get(chat_id, 0)
            if running < MAX_CONCURRENT:
                self._running[chat_id] = running + 1
                return True, None
            waiting = self._waiting.get(chat_id, 0)
            if waiting < MAX_WAITING:
                self._waiting[chat_id] = waiting + 1
                event = asyncio.Event()
                self._events.setdefault(chat_id, []).append(event)
                return True, event
            return False, None

    async def wait_turn(self, event: asyncio.Event) -> None:
        await event.wait()

    async def release(self, chat_id: int) -> None:
        async with self._lock(chat_id):
            events = self._events.get(chat_id, [])
            if events:
                events.pop(0).set()
                self._waiting[chat_id] -= 1
            else:
                running = self._running.get(chat_id, 0)
                if running > 0:
                    self._running[chat_id] = running - 1


class RedisBase:
    def __init__(self, client: aioredis.Redis | None) -> None:
        self._client = client
        self._memory: dict[str, str] = {}

    async def _get(self, key: str) -> str | None:
        if self._client:
            val = await self._client.get(key)
            return val.decode() if val else None
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
        await self._set(CACHE_PREFIX + f"lang:{mode_key}", "1" if active else "0")


class LangCodeStorage(RedisBase):
    async def get(self, mode_key: str) -> str:
        return await self._get(CACHE_PREFIX + f"lang_code:{mode_key}") or "en"

    async def set(self, mode_key: str, code: str) -> None:
        await self._set(CACHE_PREFIX + f"lang_code:{mode_key}", code)


class ReplyCounter(RedisBase):
    async def next_index(self, user_id: int, size: int) -> int:
        key = CACHE_PREFIX + f"reply:{user_id}"
        val = await self._get(key)
        index = int(val) if val else 0
        await self._set(key, str((index + 1) % size))
        return index


class AdtStorage(RedisBase):
    async def get_messages(self, mode_key: str) -> list[int]:
        val = await self._get(CACHE_PREFIX + f"adt:{mode_key}")
        return [int(x) for x in val.split(",") if x] if val else []

    async def save_messages(self, mode_key: str, msg_ids: list[int]) -> None:
        await self._set(CACHE_PREFIX + f"adt:{mode_key}", ",".join(map(str, msg_ids)))


class ButtonCycleStorage(RedisBase):
    async def get_index(self, chat_id: int) -> int:
        val = await self._get(CACHE_PREFIX + f"btn_cycle:{chat_id}")
        return int(val) if val else 0

    async def advance(self, chat_id: int, total: int) -> None:
        idx = await self.get_index(chat_id)
        await self._set(CACHE_PREFIX + f"btn_cycle:{chat_id}", str((idx + 1) % total))


class StickerSettings(RedisBase):
    async def get(self, mode_key: str) -> dict:
        val = await self._get(CACHE_PREFIX + f"sticker:{mode_key}")
        if not val:
            return {
                "enabled": False,
                "landscape": False,
                "portrait": False,
                "flip_left": False,
                "flip_right": False,
            }
        parts = val.split(",")
        return {
            "enabled": parts[0] == "1",
            "landscape": parts[1] == "1",
            "portrait": parts[2] == "1",
            "flip_left": parts[3] == "1",
            "flip_right": parts[4] == "1",
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        val = ",".join(
            "1" if settings[k] else "0"
            for k in ("enabled", "landscape", "portrait", "flip_left", "flip_right")
        )
        await self._set(CACHE_PREFIX + f"sticker:{mode_key}", val)


class FileIdCache(RedisBase):
    @staticmethod
    def _signature(mode: str, settings: dict | None) -> str:
        if mode == "sticker" and settings:
            parts = [
                "1" if settings.get(k) else "0"
                for k in ("landscape", "portrait", "flip_left", "flip_right")
            ]
            return f"sticker:{''.join(parts)}"
        return mode

    @staticmethod
    def key(url: str, mode: str, settings: dict | None = None) -> str:
        signature = FileIdCache._signature(mode, settings)
        raw = f"{url}|{signature}"
        return CACHE_PREFIX + "file_id:" + _hash_key(raw)

    async def get(self, url: str, mode: str, settings: dict | None = None) -> str | None:
        return await self._get(self.key(url, mode, settings))

    async def set(
        self, url: str, mode: str, file_id: str, settings: dict | None = None
    ) -> None:
        await self._set(self.key(url, mode, settings), file_id, ttl=FILE_ID_TTL)

    async def delete(self, url: str, mode: str, settings: dict | None = None) -> None:
        await self._del(self.key(url, mode, settings))

    @staticmethod
    def source_key(source_file_id: str, action: str, detail: str) -> str:
        raw = f"{source_file_id}|{action}|{detail}"
        return CACHE_PREFIX + "src_id:" + _hash_key(raw)

    async def get_by_source(
        self, source_file_id: str, action: str, detail: str
    ) -> str | None:
        return await self._get(self.source_key(source_file_id, action, detail))

    async def set_by_source(
        self, source_file_id: str, action: str, detail: str, file_id: str
    ) -> None:
        await self._set(
            self.source_key(source_file_id, action, detail),
            file_id,
            ttl=FILE_ID_TTL,
        )

    async def delete_by_source(
        self, source_file_id: str, action: str, detail: str
    ) -> None:
        await self._del(self.source_key(source_file_id, action, detail))


def _root(chat_id: int, bot_id: int, is_private: bool) -> str:
    return str(bot_id) if is_private else str(chat_id).removeprefix("-")


def user_dir(chat_id: int, user_id: int, bot_id: int, is_private: bool) -> str:
    path = os.path.join(BASE_DIR, _root(chat_id, bot_id, is_private), str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def cleanup(
    chat_id: int,
    user_id: int,
    bot_id: int,
    is_private: bool,
    *message_ids: int,
) -> None:
    root = _root(chat_id, bot_id, is_private)
    user_path = os.path.join(BASE_DIR, root, str(user_id))
    if os.path.isdir(user_path):
        prefixes = tuple(str(mid) for mid in message_ids if mid)
        if prefixes:
            for fname in os.listdir(user_path):
                if any(
                    fname == p
                    or fname.startswith(p + ".")
                    or fname.startswith(p + "_")
                    for p in prefixes
                ):
                    try:
                        os.remove(os.path.join(user_path, fname))
                    except OSError:
                        pass
    for path in (user_path, os.path.join(BASE_DIR, root)):
        try:
            os.rmdir(path)
        except OSError:
            pass


def _redis_client(url: str | None) -> aioredis.Redis | None:
    return aioredis.from_url(url) if url else None


def build_storage(url: str | None) -> RedisStorage | None:
    return RedisStorage.from_url(url) if url else None


def build_counter(url: str | None) -> ReplyCounter:
    return ReplyCounter(_redis_client(url))


def build_modes(url: str | None) -> ModeStorage:
    return ModeStorage(_redis_client(url))


def build_adt(url: str | None) -> AdtStorage:
    return AdtStorage(_redis_client(url))


def build_lang(url: str | None) -> LangStorage:
    return LangStorage(_redis_client(url))


def build_lang_code(url: str | None) -> LangCodeStorage:
    return LangCodeStorage(_redis_client(url))


def build_btn_cycle(url: str | None) -> ButtonCycleStorage:
    return ButtonCycleStorage(_redis_client(url))


def build_sticker(url: str | None) -> StickerSettings:
    return StickerSettings(_redis_client(url))


def build_file_cache(url: str | None) -> FileIdCache:
    return FileIdCache(_redis_client(url))


queue = ChatQueue()