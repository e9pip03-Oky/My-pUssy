import asyncio
import hashlib
import logging
import os

import redis.asyncio as aioredis
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Message

log = logging.getLogger("voicebot")
MAX_CONCURRENT = 3
MAX_WAITING = 3
BASE_DIR = "downloads"
CACHE_PREFIX = "voice:"
FILE_ID_TTL = 60 * 60 * 24 * 30


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


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ChatQueue:
    def __init__(self) -> None:
        self._slots: dict[int, asyncio.Queue[None]] = {}
        self._waiting: dict[int, int] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    def _queue(self, chat_id: int) -> asyncio.Queue[None]:
        if chat_id not in self._slots:
            queue: asyncio.Queue[None] = asyncio.Queue()
            for _ in range(MAX_CONCURRENT):
                queue.put_nowait(None)
            self._slots[chat_id] = queue
        return self._slots[chat_id]

    async def acquire(self, chat_id: int) -> tuple[bool, bool]:
        async with self._lock(chat_id):
            queue = self._queue(chat_id)
            if not queue.empty():
                queue.get_nowait()
                return True, False
            if self._waiting.get(chat_id, 0) >= MAX_WAITING:
                return False, False
            self._waiting[chat_id] = self._waiting.get(chat_id, 0) + 1
        try:
            await queue.get()
        except asyncio.CancelledError:
            async with self._lock(chat_id):
                self._waiting[chat_id] = max(0, self._waiting[chat_id] - 1)
            raise
        async with self._lock(chat_id):
            self._waiting[chat_id] = max(0, self._waiting[chat_id] - 1)
        return True, True

    async def release(self, chat_id: int) -> None:
        queue = self._queue(chat_id)
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
        await self._set(CACHE_PREFIX + f"lang:{mode_key}", "1" if active else "0")


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


class StickerSettings(RedisBase):
    async def get(self, mode_key: str) -> dict:
        value = await self._get(CACHE_PREFIX + f"sticker:{mode_key}")
        if not value:
            return {
                "enabled": False,
                "landscape": False,
                "portrait": False,
                "flip_left": False,
                "flip_right": False,
                "double_rotate": False,
                "crop_ratio": "none",
                "crop_type": "none",
            }
        parts = value.split(",")
        if len(parts) == 6:
            return {
                "enabled": parts[0] == "1",
                "landscape": parts[1] == "1",
                "portrait": parts[2] == "1",
                "flip_left": parts[3] == "1",
                "flip_right": parts[4] == "1",
                "double_rotate": False,
                "crop_ratio": parts[5] if parts[5] != "none" else "none",
                "crop_type": "none",
            }
        elif len(parts) == 7:
            return {
                "enabled": parts[0] == "1",
                "landscape": parts[1] == "1",
                "portrait": parts[2] == "1",
                "flip_left": parts[3] == "1",
                "flip_right": parts[4] == "1",
                "double_rotate": False,
                "crop_ratio": parts[5] if parts[5] != "none" else "none",
                "crop_type": parts[6] if parts[6] != "none" else "none",
            }
        return {
            "enabled": parts[0] == "1",
            "landscape": parts[1] == "1",
            "portrait": parts[2] == "1",
            "flip_left": parts[3] == "1",
            "flip_right": parts[4] == "1",
            "double_rotate": parts[5] == "1",
            "crop_ratio": parts[6] if len(parts) > 6 else "none",
            "crop_type": parts[7] if len(parts) > 7 else "none",
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        value = ",".join(
            [
                "1" if settings["enabled"] else "0",
                "1" if settings["landscape"] else "0",
                "1" if settings["portrait"] else "0",
                "1" if settings["flip_left"] else "0",
                "1" if settings["flip_right"] else "0",
                "1" if settings.get("double_rotate") else "0",
                settings.get("crop_ratio", "none"),
                settings.get("crop_type", "none"),
            ]
        )
        await self._set(CACHE_PREFIX + f"sticker:{mode_key}", value)


class DefaultSettings(RedisBase):
    async def get(self, mode_key: str) -> dict:
        value = await self._get(CACHE_PREFIX + f"default:{mode_key}")
        if not value:
            return {"enabled": False, "send_as": "document"}
        parts = value.split(",")
        return {
            "enabled": parts[0] == "1",
            "send_as": (
                parts[1]
                if len(parts) > 1 and parts[1] in ("document", "video")
                else "document"
            ),
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        value = ",".join(
            [
                "1" if settings["enabled"] else "0",
                "video" if settings.get("send_as") == "video" else "document",
            ]
        )
        await self._set(CACHE_PREFIX + f"default:{mode_key}", value)


class FileIdCache(RedisBase):
    @staticmethod
    def _signature(mode: str, settings: dict | None) -> str:
        if mode == "sticker" and settings:
            parts = [
                "1" if settings.get(key) else "0"
                for key in (
                    "landscape",
                    "portrait",
                    "flip_left",
                    "flip_right",
                    "double_rotate",
                )
            ]
            parts.append(settings.get("crop_ratio", "none"))
            parts.append(settings.get("crop_type", "none"))
            return f"sticker:{'_'.join(parts)}"

        if mode == "default" and settings:
            send_as = settings.get("send_as", "document")
            return f"default:{send_as}"

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
            self.source_key(source_file_id, action, detail), file_id, ttl=FILE_ID_TTL
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
    chat_id: int, user_id: int, bot_id: int, is_private: bool, *message_ids: int
) -> None:
    root = _root(chat_id, bot_id, is_private)
    user_path = os.path.join(BASE_DIR, root, str(user_id))
    if os.path.isdir(user_path):
        prefixes = tuple(str(message_id) for message_id in message_ids if message_id)
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


def _redis_client(url: str | None) -> aioredis.Redis | None:
    if not url:
        return None
    return aioredis.from_url(url, health_check_interval=48, socket_keepalive=True)


def build_storage(url: str | None) -> RedisStorage | None:
    return (
        RedisStorage.from_url(url, health_check_interval=48, socket_keepalive=True)
        if url
        else None
    )


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


def build_default(url: str | None) -> DefaultSettings:
    return DefaultSettings(_redis_client(url))


def build_file_cache(url: str | None) -> FileIdCache:
    return FileIdCache(_redis_client(url))


queue = ChatQueue()