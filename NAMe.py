import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

TELEGRAM_HOSTS = {
    "t.me",
    "telegram.me",
    "www.telegram.me",
}


class DownloadQueue:
    def __init__(self, running_limit=3, waiting_limit=3):
        self.running_limit = running_limit
        self.waiting_limit = waiting_limit
        self.running = 0
        self.waiting = 0
        self.condition = asyncio.Condition()

    async def acquire(self):
        async with self.condition:
            if self.running < self.running_limit:
                self.running += 1
                return True

            if self.waiting >= self.waiting_limit:
                return False

            self.waiting += 1
            try:
                while self.running >= self.running_limit:
                    await self.condition.wait()
                self.waiting -= 1
                self.running += 1
                return True
            except BaseException:
                self.waiting -= 1
                self.condition.notify_all()
                raise

    async def release(self):
        async with self.condition:
            self.running = max(0, self.running - 1)
            self.condition.notify()


class QueueManager:
    def __init__(self):
        self.queues = {}
        self.lock = asyncio.Lock()

    async def acquire(self, scope):
        async with self.lock:
            queue = self.queues.setdefault(scope, DownloadQueue())
        return queue if await queue.acquire() else None

    async def release(self, scope, queue):
        await queue.release()
        async with self.lock:
            if queue.running == 0 and queue.waiting == 0:
                self.queues.pop(scope, None)


def scope_key(chat_type, chat_id, user_id, thread_id):
    if chat_type == "private":
        return f"private:{user_id}"
    if thread_id is not None:
        return f"topic:{chat_id}:{thread_id}"
    return f"chat:{chat_id}"


def is_telegram_link(text):
    parsed = urlparse(text.strip())
    return parsed.netloc.lower() in TELEGRAM_HOSTS


def _clean(value):
    value = value or ""
    result = []
    uppercase = set("ATFGUJNML")

    for char in value:
        if char.isascii() and char.isalpha():
            char = char.lower()
            if char.upper() in uppercase:
                char = char.upper()
            result.append(char)
        elif char.isalnum() or char.isspace() or char in "_&-":
            result.append(char)

    return re.sub(r"\s+", " ", "".join(result)).strip()


def make_filename(info):
    publisher = info.get("uploader") or info.get("channel") or ""
    title = info.get("title")

    if not title:
        date = info.get("upload_date")
        if date and len(date) == 8:
            title = f"{int(date[:4])}/{int(date[4:6])}/{int(date[6:8])}"
        else:
            timestamp = info.get("timestamp")
            title = (
                datetime.fromtimestamp(timestamp).strftime("%Y/%-m/%-d")
                if timestamp
                else "download"
            )

    publisher = _clean(publisher)
    title = _clean(title)
    return " - ".join(part for part in (publisher, title) if part) or "download"


def job_directory(base, scope):
    path = Path(base) / re.sub(r"-", "", str(scope))
    path.mkdir(parents=True, exist_ok=True)
    return path
