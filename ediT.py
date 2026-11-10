import logging
import mimetypes
import os
import random
import re

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import EDIT_FAIL_MSG, EDIT_SEPARATOR_MSG, EDIT_START_BIGGER_MSG
from cAsh import cleanup, safe_delete, user_dir
from cAsh_Two import FileIdCache
from yTFMe import (
    MAX_FILESIZE,
    trim_animation,
    trim_audio,
    trim_note,
    trim_video,
    trim_voice,
)

log = logging.getLogger("voicebot")

EDIT_STATE = {}

MEDIA_FIELDS = ("voice", "audio", "video_note", "animation", "video")
TRIM_FUNCS = {
    "voice": (trim_voice, "reply_voice"),
    "audio": (trim_audio, "reply_audio"),
    "video_note": (trim_note, "reply_video_note"),
    "animation": (trim_animation, "reply_animation"),
    "video": (trim_video, "reply_video"),
}

OUTPUT_EXTS = {
    "voice": ".ogg",
    "audio": None,
    "video_note": ".mp4",
    "animation": ".mp4",
    "video": None,
}


def _detect_ext(media, in_path: str, media_type: str) -> str:
    forced = OUTPUT_EXTS.get(media_type)
    if forced:
        return forced
    ext = os.path.splitext(in_path)[1]
    if ext:
        return ext
    file_name = getattr(media, "file_name", None)
    if file_name:
        ext = os.path.splitext(file_name)[1]
        if ext:
            return ext
    mime = getattr(media, "mime_type", None)
    if mime:
        guessed = mimetypes.guess_extension(mime.split(";")[0].strip())
        if guessed:
            return guessed
    return ""


def _parse_time(value: str) -> float | None:
    microseconds = 0.0
    if "." in value:
        main_part, micro_part = value.split(".", 1)
        if not micro_part.isdigit() or int(micro_part) > 60:
            return None
        microseconds = int(micro_part) / 60.0
    else:
        main_part = value
    parts = main_part.split(":")
    if len(parts) > 3:
        return None
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        if numbers[0] > 24 or numbers[1] > 60 or numbers[2] > 60:
            return None
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2] + microseconds
    if len(numbers) == 2:
        if numbers[0] > 60 or numbers[1] > 60:
            return None
        return numbers[0] * 60 + numbers[1] + microseconds
    if len(numbers) == 1:
        if numbers[0] > 60:
            return None
        return numbers[0] + microseconds
    return None


def _parse_range(text: str) -> tuple[str, str] | str:
    cleaned = re.sub(r"(?<=\s)[/\-](?=\s)", " ", text.strip())
    segments = [seg for seg in cleaned.split() if seg]
    if len(segments) == 1:
        end_value = segments[0]
        if _parse_time(end_value) is None:
            return "format"
        return "0", end_value
    if len(segments) == 2:
        start_value, end_value = segments
        start_seconds, end_seconds = _parse_time(start_value), _parse_time(end_value)
        if start_seconds is None or end_seconds is None:
            return "format"
        if start_seconds >= end_seconds:
            return "bigger"
        return start_value, end_value
    return "format"


async def set_edit_state(message: Message, bot: Bot) -> None:
    reply_message = await message.reply(EDIT_SEPARATOR_MSG)
    EDIT_STATE[message.from_user.id] = {
        "msg": message.reply_to_message,
        "prompt": reply_message,
    }


def _media_of(media_message: Message) -> tuple[str, str, object] | None:
    for field in MEDIA_FIELDS:
        media = getattr(media_message, field, None)
        if media:
            return field, media.file_id, media
    return None


async def _reply_cached(message: Message, media_type: str, file_id: str) -> bool:
    try:
        await getattr(message, TRIM_FUNCS[media_type][1])(file_id)
        return True
    except Exception:
        return False


async def handle_pending_edit(
    message: Message, bot: Bot, file_cache: FileIdCache
) -> bool:
    user_id = message.from_user.id
    if user_id not in EDIT_STATE:
        return False
    state = EDIT_STATE.pop(user_id)
    media_message = state["msg"]
    prompt_message = state["prompt"]

    media_info = _media_of(media_message)
    if not media_info:
        return False
    media_type, file_id, media = media_info

    parsed = _parse_range(message.text)
    if parsed == "format":
        await message.reply(EDIT_FAIL_MSG)
        return True
    if parsed == "bigger":
        await message.reply(EDIT_START_BIGGER_MSG)
        return True
    start_value, end_value = parsed

    detail = f"{start_value}:{end_value}"
    cache_action = f"edit_{media_type}"

    cached = await file_cache.get_by_source(file_id, cache_action, detail)
    if cached:
        if await _reply_cached(message, media_type, cached):
            await safe_delete(prompt_message)
            return True
        await file_cache.delete_by_source(file_id, cache_action, detail)

    await safe_delete(prompt_message)

    chat_id = message.chat.id
    is_private = message.chat.type == "private"
    workdir = user_dir(chat_id, user_id, bot.id, is_private)
    temp_id = random.randint(100000, 999999)

    out_path = os.path.join(workdir, f"{temp_id}_edit")

    try:
        telegram_file = await bot.get_file(file_id)
        file_ext = os.path.splitext(telegram_file.file_path)[1]
        in_path = os.path.join(workdir, f"{temp_id}_{media_type}{file_ext}")
        await bot.download_file(telegram_file.file_path, in_path)

        if os.path.getsize(in_path) > MAX_FILESIZE:
            await message.reply(EDIT_FAIL_MSG)
            return True

        trim_func, reply_method = TRIM_FUNCS[media_type]
        ext = _detect_ext(media, in_path, media_type)
        out_path += ext

        if not await trim_func(in_path, out_path, start_value, end_value):
            await message.reply(EDIT_FAIL_MSG)
            return True

        sent = await getattr(message, reply_method)(FSInputFile(out_path))
        media_obj = getattr(sent, media_type, None)
        if media_obj:
            await file_cache.set_by_source(
                file_id, cache_action, detail, media_obj.file_id
            )
    except Exception:
        await message.reply(EDIT_FAIL_MSG)
    finally:
        cleanup(chat_id, user_id, bot.id, is_private, temp_id)
    return True