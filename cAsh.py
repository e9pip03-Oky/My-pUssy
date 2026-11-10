import asyncio  
import hashlib  
import logging  
import os  
  
import redis.asyncio as aioredis  
from aiogram.fsm.storage.redis import RedisStorage  
from aiogram.types import Message  
  
log = logging.getLogger("voicebot")  
  
MAX_CONCURRENT = 3  
MAX_WAITING = 18  
BASE_DIR = "downloads"  
CACHE_PREFIX = "voice:"  
PENDING_TTL = 6 * 60 * 60  
  
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
    def __init__(self, client: aioredis.Redis) -> None:  
        self._client = client  
  
    async def _get(self, key: str) -> str | None:  
        value = await self._client.get(key)  
        return value.decode() if value else None  
  
    async def _set(self, key: str, value: str, ttl: int | None = None) -> None:  
        if ttl:  
            await self._client.set(key, value, ex=ttl)  
        else:  
            await self._client.set(key, value)  
  
    async def _del(self, key: str) -> None:  
        await self._client.delete(key)  
  
  
class ModeStorage(RedisBase):  
    async def get(self, mode_key: str) -> str:  
        return await self._get(CACHE_PREFIX + f"mode:{mode_key}") or "voice"  
  
    async def set(self, mode_key: str, mode: str) -> None:  
        await self._set(CACHE_PREFIX + f"mode:{mode_key}", mode)  
  
    async def get_previous(self, mode_key: str) -> str:  
        return await self._get(CACHE_PREFIX + f"prev_mode:{mode_key}") or "voice"  
  
    async def set_previous(self, mode_key: str, mode: str) -> None:  
        await self._set(CACHE_PREFIX + f"prev_mode:{mode_key}", mode)  
  
    async def get_last_menu(self, mode_key: str) -> str:  
        return await self._get(CACHE_PREFIX + f"last_menu:{mode_key}") or "main"  
  
    async def set_last_menu(self, mode_key: str, menu: str) -> None:  
        await self._set(CACHE_PREFIX + f"last_menu:{mode_key}", menu)  
  
  
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
    prune_downloads()  
  
  
def _redis_client(url: str) -> aioredis.Redis:  
    return aioredis.from_url(url, health_check_interval=48, socket_keepalive=True)  
  
  
def build_storage(url: str) -> RedisStorage:  
    return RedisStorage.from_url(url, health_check_interval=48, socket_keepalive=True)  
  
  
def build_counter(url: str) -> ReplyCounter:  
    return ReplyCounter(_redis_client(url))  
  
  
def build_modes(url: str) -> ModeStorage:  
    return ModeStorage(_redis_client(url))  
  
  
def build_lang(url: str) -> LangStorage:  
    return LangStorage(_redis_client(url))  
  
  
def build_lang_code(url: str) -> LangCodeStorage:  
    return LangCodeStorage(_redis_client(url))  
  
  
def build_btn_cycle(url: str) -> ButtonCycleStorage:  
    return ButtonCycleStorage(_redis_client(url))  
  
  
def build_notif(url: str) -> NotifStorage:  
    return NotifStorage(_redis_client(url))  
  
  
def build_allowed(url: str) -> AllowedStorage:  
    return AllowedStorage(_redis_client(url))  
  
  
def build_pending(url: str) -> PendingStorage:  
    return PendingStorage(_redis_client(url))  
  
  
queue = ChatQueue()
