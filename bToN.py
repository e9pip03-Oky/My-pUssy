import asyncio
import hashlib
import os
import shutil
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

_DOWNLOAD_DIRECTORY_LOCK = asyncio.Lock()
_ACTIVE_USER_DIRECTORIES = {}
_ACTIVE_GROUP_DIRECTORIES = {}


async def _await_cleanup(awaitable):
    task = asyncio.ensure_future(awaitable)
    cancelled = False

    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True

    result = task.result()

    if cancelled:
        raise asyncio.CancelledError

    return result


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


def download_directory(
    user_id,
    chat_id=None,
    chat_type=None,
):
    if chat_type in {
        "group",
        "supergroup",
    }:
        return (
            Path(DOWNLOADS_DIR)
            / str(chat_id)
            / str(user_id)
        )

    return (
        Path(DOWNLOADS_DIR)
        / str(user_id)
    )


def group_download_directory(chat_id):
    return (
        Path(DOWNLOADS_DIR)
        / str(chat_id)
    )


def _reset_downloads_directory():
    directory = Path(DOWNLOADS_DIR)

    if (
        directory.is_symlink()
        or directory.is_file()
    ):
        directory.unlink()
    elif directory.exists():
        shutil.rmtree(directory)

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )


async def cleanup_previous_downloads():
    async with _DOWNLOAD_DIRECTORY_LOCK:
        try:
            await _await_cleanup(
                asyncio.to_thread(
                    _reset_downloads_directory
                )
            )
        finally:
            _ACTIVE_USER_DIRECTORIES.clear()
            _ACTIVE_GROUP_DIRECTORIES.clear()


def _active_group_count(group_directory):
    return sum(
        count
        for user_directory, count
        in _ACTIVE_USER_DIRECTORIES.items()
        if (
            count > 0
            and user_directory.parent == group_directory
        )
    )


async def acquire_download_directory(
    user_id,
    chat_id,
    chat_type,
):
    user_directory = download_directory(
        user_id,
        chat_id,
        chat_type,
    )

    group_directory = None

    if chat_type in {
        "group",
        "supergroup",
    }:
        group_directory = (
            group_download_directory(
                chat_id
            )
        )

    async with _DOWNLOAD_DIRECTORY_LOCK:
        if group_directory is not None:
            group_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

        user_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        _ACTIVE_USER_DIRECTORIES[
            user_directory
        ] = (
            _ACTIVE_USER_DIRECTORIES.get(
                user_directory,
                0,
            )
            + 1
        )

        if group_directory is not None:
            _ACTIVE_GROUP_DIRECTORIES[
                group_directory
            ] = _active_group_count(
                group_directory
            )

    return user_directory


async def _remove_released_directories(
    user_directory,
    remove_user_directory,
    group_directory,
    remove_group_directory,
):
    if remove_user_directory:
        await asyncio.to_thread(
            shutil.rmtree,
            user_directory,
            True,
        )

    if remove_group_directory:
        await asyncio.to_thread(
            shutil.rmtree,
            group_directory,
            True,
        )


async def release_download_directory(
    user_id,
    chat_id,
    chat_type,
):
    user_directory = download_directory(
        user_id,
        chat_id,
        chat_type,
    )

    group_directory = None

    if chat_type in {
        "group",
        "supergroup",
    }:
        group_directory = (
            group_download_directory(
                chat_id
            )
        )

    async with _DOWNLOAD_DIRECTORY_LOCK:
        user_count = _ACTIVE_USER_DIRECTORIES.get(
            user_directory,
            0,
        )

        remove_user_directory = user_count <= 1

        if user_count > 1:
            _ACTIVE_USER_DIRECTORIES[
                user_directory
            ] = user_count - 1
        else:
            _ACTIVE_USER_DIRECTORIES.pop(
                user_directory,
                None,
            )

        remove_group_directory = False

        if group_directory is not None:
            group_count = _active_group_count(
                group_directory
            )

            if group_count > 0:
                _ACTIVE_GROUP_DIRECTORIES[
                    group_directory
                ] = group_count
            else:
                _ACTIVE_GROUP_DIRECTORIES.pop(
                    group_directory,
                    None,
                )
                remove_group_directory = True

        if (
            remove_user_directory
            or remove_group_directory
        ):
            await _await_cleanup(
                _remove_released_directories(
                    user_directory,
                    remove_user_directory,
                    group_directory,
                    remove_group_directory,
                )
            )


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
