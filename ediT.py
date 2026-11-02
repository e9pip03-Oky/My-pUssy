import logging
import os
import random
import re

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import EDIT_FAIL_MSG, EDIT_SEPARATOR_MSG, EDIT_START_BIGGER_MSG
from cAsh import FileIdCache, cleanup, safe_delete, user_dir
from yTFMe import MAX_FILESIZE, trim_note, trim_video, trim_voice

log = logging.getLogger("voicebot")
EDIT_STATE = {}


def _parse_time(value: str) -> float | None:
    microseconds = 0.0
    if "." in value:
        main_part, micro_part = value.split(".", 1)
        if not micro_part.isdigit():
            return None
        if int(micro_part) > 60:
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


async def set_edit_state(message: Message, bot: Bot) -> None:
    reply_message = await message.reply(EDIT_SEPARATOR_MSG)
    EDIT_STATE[message.from_user.id] = {
        "msg": message.reply_to_message,
        "prompt": reply_message,
    }


async def handle_pending_edit(
    message: Message, bot: Bot, file_cache: FileIdCache
) -> bool:
    user_id = message.from_user.id
    if user_id not in EDIT_STATE:
        return False
    state = EDIT_STATE.pop(user_id)
    media_message = state["msg"]
    prompt_message = state["prompt"]

    if media_message.voice:
        media_type = "voice"
        file_id = media_message.voice.file_id
    elif media_message.video_note:
        media_type = "note"
        file_id = media_message.video_note.file_id
    elif media_message.animation:
        media_type = "sticker"
        file_id = media_message.animation.file_id
    elif media_message.video:
        media_type = "video"
        file_id = media_message.video.file_id
    else:
        return False

    text_value = message.text.strip()
    clean_text = re.sub(r"[/\-]", " ", text_value)
    segments = [segment for segment in clean_text.split() if segment]

    if len(segments) == 1:
        start_value = "0"
        end_value = segments[0].strip()
        end_seconds = _parse_time(end_value)
        if end_seconds is None:
            await message.reply(EDIT_SEPARATOR_MSG)
            return True
    elif len(segments) == 2:
        start_value, end_value = segments[0].strip(), segments[1].strip()
        start_seconds, end_seconds = _parse_time(start_value), _parse_time(end_value)
        if start_seconds is None or end_seconds is None:
            await message.reply(EDIT_SEPARATOR_MSG)
            return True
        if start_seconds >= end_seconds:
            await message.reply(EDIT_START_BIGGER_MSG)
            return True
    else:
        await message.reply(EDIT_SEPARATOR_MSG)
        return True

    detail = f"{start_value}:{end_value}"
    cached = await file_cache.get_by_source(file_id, f"edit_{media_type}", detail)
    if cached:
        try:
            if media_type == "voice":
                await message.reply_voice(cached)
            elif media_type == "note":
                await message.reply_video_note(cached)
            elif media_type == "sticker":
                await message.reply_animation(cached)
            else:
                await message.reply_video(cached)
            await safe_delete(prompt_message)
            return True
        except Exception:
            await file_cache.delete_by_source(file_id, f"edit_{media_type}", detail)

    await safe_delete(prompt_message)

    chat_id = message.chat.id
    is_private = message.chat.type == "private"
    workdir = user_dir(chat_id, user_id, bot.id, is_private)

    temp_id = random.randint(100000, 999999)

    in_path = os.path.join(workdir, f"{temp_id}_in")
    out_path = os.path.join(workdir, f"{temp_id}_out")
    try:
        telegram_file = await bot.get_file(file_id)
        await bot.download_file(telegram_file.file_path, in_path)
        if os.path.getsize(in_path) > MAX_FILESIZE:
            await message.reply(EDIT_FAIL_MSG)
            return True

        if media_type == "voice":
            out_path += ".ogg"
            success = await trim_voice(in_path, out_path, start_value, end_value)
            if success:
                sent = await message.reply_voice(FSInputFile(out_path))
                await file_cache.set_by_source(
                    file_id, f"edit_{media_type}", detail, sent.voice.file_id
                )
        elif media_type == "note":
            out_path += ".mp4"
            success = await trim_note(in_path, out_path, start_value, end_value)
            if success:
                sent = await message.reply_video_note(FSInputFile(out_path))
                await file_cache.set_by_source(
                    file_id, f"edit_{media_type}", detail, sent.video_note.file_id
                )
        elif media_type == "sticker":
            out_path += ".mp4"
            success = await trim_video(in_path, out_path, start_value, end_value)
            if success:
                sent = await message.reply_animation(FSInputFile(out_path))
                await file_cache.set_by_source(
                    file_id, f"edit_{media_type}", detail, sent.animation.file_id
                )
        else:
            ext = os.path.splitext(in_path)[1]
            out_path += ext
            success = await trim_video(in_path, out_path, start_value, end_value)
            if success:
                sent = await message.reply_video(FSInputFile(out_path))
                await file_cache.set_by_source(
                    file_id, f"edit_{media_type}", detail, sent.video.file_id
                )
        if not success:
            await message.reply(EDIT_FAIL_MSG)
    except Exception:
        await message.reply(EDIT_FAIL_MSG)
    finally:
        cleanup(
            chat_id,
            user_id,
            bot.id,
            is_private,
            temp_id,
        )
    return True