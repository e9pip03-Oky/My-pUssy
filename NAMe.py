import re
import asyncio
from typing import Dict, Optional, Set


class UserQueueManager:
    def __init__(self):
        self.user_semaphores: Dict[int, asyncio.Semaphore] = {}
        self.user_active_count: Dict[int, int] = {}
        self.user_queues: Dict[int, asyncio.Queue] = {}

    def is_user_blocked(self, user_id: int) -> bool:
        active = self.user_active_count.get(user_id, 0)
        queue_size = self.user_queues[user_id].qsize() if user_id in self.user_queues else 0
        return (active + queue_size) >= 6

    def get_semaphore(self, user_id: int) -> asyncio.Semaphore:
        if user_id not in self.user_semaphores:
            self.user_semaphores[user_id] = asyncio.Semaphore(3)
        return self.user_semaphores[user_id]

    async def acquire_slot(self, user_id: int) -> bool:
        if self.is_user_blocked(user_id):
            return False

        if user_id not in self.user_queues:
            self.user_queues[user_id] = asyncio.Queue(maxsize=3)

        self.user_active_count[user_id] = self.user_active_count.get(user_id, 0) + 1
        return True

    def release_slot(self, user_id: int):
        if user_id in self.user_active_count:
            self.user_active_count[user_id] -= 1
            if self.user_active_count[user_id] <= 0:
                del self.user_active_count[user_id]
                if user_id in self.user_semaphores:
                    del self.user_semaphores[user_id]
                if user_id in self.user_queues:
                    del self.user_queues[user_id]


queue_manager = UserQueueManager()


def is_telegram_link(text: str) -> bool:
    pattern = r"(https?://)?(www\.)?(t\.me|telegram\.me|telegram\.dog)/[a-zA-Z0-9_]+"
    return bool(re.search(pattern, text))


def extract_url(text: str) -> Optional[str]:
    if is_telegram_link(text):
        return None
    url_pattern = r"https?://[^\s]+"
    match = re.search(url_pattern, text)
    if match:
        return match.group(0)
    return None


def format_custom_filename(uploader: str, title: str) -> str:
    raw_name = f"{uploader} - {title}" if uploader else title
    allowed_uppercase: Set[str] = {"A", "T", "F", "G", "U", "J", "N", "M", "L"}

    formatted_chars = []
    for char in raw_name:
        if char == "_" or char == " " or char == "-":
            formatted_chars.append(char)
        elif char.isalpha():
            if char.isupper():
                if char in allowed_uppercase:
                    formatted_chars.append(char)
                else:
                    formatted_chars.append(char.lower())
            else:
                formatted_chars.append(char)
        elif char.isdigit():
            formatted_chars.append(char)

    result = "".join(formatted_chars)
    result = re.sub(r"\s+", " ", result).strip()
    return result if result else "file"
