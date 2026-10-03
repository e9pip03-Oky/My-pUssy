import re
import asyncio

UPPER_ALLOWED = set("ATFGUJNML")

class QueueManager:
    def __init__(self):
        self.active_downloads = {}
        self.user_queues = {}
        self.locks = {}

    def _get_lock(self, key: str):
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        return self.locks[key]

    async def can_accept_task(self, key: str) -> bool:
        async with self._get_lock(key):
            active = self.active_downloads.get(key, 0)
            queue = self.user_queues.get(key, [])
            if active < 3:
                return True
            if len(queue) < 3:
                return True
            return False

    async def register_task(self, key: str, url: str) -> bool:
        async with self._get_lock(key):
            active = self.active_downloads.get(key, 0)
            if active < 3:
                self.active_downloads[key] = active + 1
                return True
            queue = self.user_queues.setdefault(key, [])
            if len(queue) < 3:
                queue.append(url)
                return False
            return False

    async def release_task(self, key: str):
        async with self._get_lock(key):
            active = self.active_downloads.get(key, 0)
            queue = self.user_queues.get(key, [])
            if queue:
                queue.pop(0)
            else:
                if active > 0:
                    self.active_downloads[key] = active - 1

def is_telegram_link(url: str) -> bool:
    pattern = r'https?://(t\.me|telegram\.me|telegram\.dog)/'
    return bool(re.search(pattern, url, re.IGNORECASE))

def format_title_case(text: str) -> str:
    result = []
    for char in text:
        if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
            upper_char = char.upper()
            if upper_char in UPPER_ALLOWED:
                result.append(upper_char)
            else:
                result.append(char.lower())
        else:
            result.append(char)
    return "".join(result)

def sanitize_component(text: str) -> str:
    text = re.sub(r'[^\w\s]', '', text)
    text = text.replace('_', '___TEMP___')
    text = text.replace('_', '')
    text = text.replace('___TEMP___', '_')
    return text.strip()

def build_filename(uploader_or_channel: str, title: str) -> str:
    clean_uploader = sanitize_component(uploader_or_channel)
    clean_title = sanitize_component(title)

    raw_name = f"{clean_uploader} - {clean_title}"
    return format_title_case(raw_name)

queue_mgr = QueueManager()
