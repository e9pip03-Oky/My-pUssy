import asyncio
import hashlib
import logging
import os
import time

import redis.asyncio as aioredis
from aiogram.fsm.storage.redis import RedisStorage

log = logging.getLogger("voicebot")

MAX_CONCURRENT = 3
MAX_WAITING = 3
BASE_DIR = "downloads"
CACHE_PREFIX = "voice:"
FILE_ID_TTL = 60 * 60 * 24 * 30
REDIS_IDLE_TIMEOUT = 60


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
                return

            running = self._running.get(chat_id, 0)
            if running > 0:
                self._running[chat_id] = running - 1


class RedisManager:
    def __init__(self, url: str | None) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None
        self._last_used: float = 0.0
        self._timer: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def get(self) -> aioredis.Redis | None:
        if not self._url:
            return None

        async with self._lock:
            if self._closed:
                return None

            if self._client is None:
                self._client = aioredis.from_url(self._url)
                log.info("redis: client created")

            self._last_used = time.monotonic()
            self._schedule_idle()
            return self._client

    def _schedule_idle(self) -> None:
        if self._timer:
            self._timer.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        self._timer = loop.call_later(REDIS_IDLE_TIMEOUT, self._idle_tick)

    def _idle_tick(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.create_task(self._maybe_close())

    async def _maybe_close(self) -> None:
        async with self._lock:
            if self._closed or self._client is None:
                return

            if time.monotonic() - self._last_used < REDIS_IDLE_TIMEOUT:
                self._schedule_idle()
                return

            try:
                await self._client.aclose()
                log.info("redis: client closed (idle)")
            except Exception as exc:
                log.warning("redis idle close failed: %s", exc)
            finally:
                self._client = None

    async def close(self) -> None:
        async with self._lock:
            self._closed = True

            if self._timer:
                self._timer.cancel()
                self._timer = None

            if self._client is not None:
                try:
                    await self._client.aclose()
                    log.info("redis: client closed (shutdown)")
                except Exception as exc:
                    log.warning("redis shutdown close failed: %s", exc)
                finally:
                    self._client = None


class RedisBase:
    def __init__(self, manager: RedisManager | None) -> None:
        self._manager = manager
        self._memory: dict[str, tuple[str, float | None]] = {}

    async def _client(self) -> aioredis.Redis | None:
        if self._manager is None:
            return None
        return await self._manager.get()

    async def _get(self, key: str) -> str | None:
        client = await self._client()
        if client:
            val = await client.get(key)
            return val.decode() if val else None

        item = self._memory.get(key)
        if not item:
            return None

        val, exp = item
        if exp and time.monotonic() > exp:
            self._memory.pop(key, None)
            return None

        return val

    async def _set(self, key: str, value: str, ttl: int | None = None) -> None:
        client = await self._client()
        if client:
            if ttl:
                await client.set(key, value, ex=ttl)
            else:
                await client.set(key, value)
            return

        exp = time.monotonic() + ttl if ttl else None
        self._memory[key] = (value, exp)

    async def _del(self, key: str) -> None:
        client = await self._client()
        if client:
            await client.delete(key)
            return

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
                "crop_ratio": "none",
                "crop_type": "none",
            }

        parts = val.split(",")
        return {
            "enabled": parts[0] == "1",
            "landscape": parts[1] == "1",
            "portrait": parts[2] == "1",
            "flip_left": parts[3] == "1",
            "flip_right": parts[4] == "1",
            "crop_ratio": parts[5] if len(parts) > 5 else "none",
            "crop_type": parts[6] if len(parts) > 6 else "none",
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        val = ",".join(
            [
                "1" if settings["enabled"] else "0",
                "1" if settings["landscape"] else "0",
                "1" if settings["portrait"] else "0",
                "1" if settings["flip_left"] else "0",
                "1" if settings["flip_right"] else "0",
                settings.get("crop_ratio", "none"),
                settings.get("crop_type", "none"),
            ]
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
            parts.append(settings.get("crop_ratio", "none"))
            parts.append(settings.get("crop_type", "none"))
            return f"sticker:{'_'.join(parts)}"
        return mode

    @staticmethod
    def key(url: str, mode: str, settings: dict | None = None) -> str:
        signature = FileIdCache._signature(mode, settings)
        raw = f"{url}|{signature}"
        return CACHE_PREFIX + "file_id:" + _hash_key(raw)

    async def get(
        self, url: str, mode: str, settings: dict | None = None
    ) -> str | None:
        return await self._get(self.key(url, mode, settings))

    async def set(
        self, url: str, mode: str, file_id: str, settings: dict | None = None
    ) -> None:
        await self._set(self.key(url, mode, settings), file_id, ttl=FILE_ID_TTL)

    async def delete(
        self, url: str, mode: str, settings: dict | None = None
    ) -> None:
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


def build_storage(url: str | None) -> RedisStorage | None:
    return RedisStorage.from_url(url) if url else None


def build_manager(url: str | None) -> RedisManager:
    return RedisManager(url)


def build_counter(manager: RedisManager | None) -> ReplyCounter:
    return ReplyCounter(manager)


def build_modes(manager: RedisManager | None) -> ModeStorage:
    return ModeStorage(manager)


def build_adt(manager: RedisManager | None) -> AdtStorage:
    return AdtStorage(manager)


def build_lang(manager: RedisManager | None) -> LangStorage:
    return LangStorage(manager)


def build_lang_code(manager: RedisManager | None) -> LangCodeStorage:
    return LangCodeStorage(manager)


def build_btn_cycle(manager: RedisManager | None) -> ButtonCycleStorage:
    return ButtonCycleStorage(manager)


def build_sticker(manager: RedisManager | None) -> StickerSettings:
    return StickerSettings(manager)


def build_file_cache(manager: RedisManager | None) -> FileIdCache:
    return FileIdCache(manager)


queue = ChatQueue()