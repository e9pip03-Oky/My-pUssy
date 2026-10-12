import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse


MODE_NORMAL = "normal"
MODE_VOICE = "voice"

MEDIA_TYPE_DOCUMENT = "document"
MEDIA_TYPE_VOICE = "voice"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_PHOTO = "photo"
MEDIA_TYPE_AUDIO = "audio"
MEDIA_TYPE_ANIMATION = "animation"
MEDIA_TYPE_VIDEO_NOTE = "video_note"

STYLE_PRIMARY = "primary"
STYLE_DANGER = "danger"
STYLE_SUCCESS = "success"

MAX_ACTIVE_DOWNLOADS = 2
MAX_QUEUED_DOWNLOADS = 3
ALBUM_BATCH_SIZE = 8

DOWNLOADS_DIR = "downloads"

BOT_TOKEN_ENV = "BOT_TOKEN"
DB_PATH_ENV = "DB_PATH"
TAKEOFF_ENV = "boT_TAkeoFF"
FFMPEG_PATH_ENV = "FFMPEG_PATH"

DEFAULT_DB_PATH = "cache.db"

CALLBACK_PREFIX = "mode:"

TELEGRAM_HOSTS = {
    "t.me",
    "telegram.me",
    "telegram.dog",
}

ADMIN_STATUSES = {
    "administrator",
    "creator",
}


def get_bot_token():
    return os.getenv(
        BOT_TOKEN_ENV,
        "",
    )


def get_db_path():
    return os.getenv(
        DB_PATH_ENV,
        DEFAULT_DB_PATH,
    )


def get_ffmpeg_path():
    return os.getenv(
        FFMPEG_PATH_ENV
    )


def get_takeoff_ids():
    value = os.getenv(
        TAKEOFF_ENV,
        "",
    )

    return tuple(
        item
        for item in value.split("/")
        if item
    )


def settings_key(
    chat_id,
    user_id=None,
    thread_id=None,
    chat_type=None,
):
    if chat_type == "private":
        return f"user:{user_id}"

    if (
        chat_type == "supergroup"
        and thread_id
    ):
        return (
            f"chat:{chat_id}:"
            f"topic:{thread_id}"
        )

    return f"chat:{chat_id}"


def mode_callback(mode):
    return f"{CALLBACK_PREFIX}{mode}"


def parse_mode_callback(data):
    if not data.startswith(
        CALLBACK_PREFIX
    ):
        return None

    return data[
        len(CALLBACK_PREFIX):
    ]


def next_mode(mode):
    if mode == MODE_VOICE:
        return MODE_NORMAL

    return MODE_VOICE


def download_directory(user_id):
    return Path(
        DOWNLOADS_DIR
    ) / str(user_id)


def cache_key(
    mode,
    media_type,
    value,
):
    data = (
        f"{mode}:{media_type}:{value}"
    )

    return hashlib.sha256(
        data.encode("utf-8")
    ).hexdigest()


def is_telegram_url(url):
    value = url.strip()

    if "://" not in value:
        value = f"https://{value}"

    host = urlparse(value).hostname

    if not host:
        return False

    host = host.lower().rstrip(".")

    return any(
        host == item
        or host.endswith(f".{item}")
        for item in TELEGRAM_HOSTS
    )