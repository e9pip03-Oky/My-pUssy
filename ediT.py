import logging
import os
import re

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import (
    EDIT_KEYWORDS, EDIT_SEPARATOR_MSG, EDIT_START_BIGGER_MSG, EDIT_FAIL_MSG, EDIT_END_TOO_LONG_MSG
)
from cAsh import cleanup, user_dir
from yTFMe import trim_voice

log = logging.getLogger("voicebot")

EDIT_STATE = {}


def _parse_time(t: str) -> float | None:
    micro_val = 0.0
    if "." in t:
        main_part, micro_part = t.split(".", 1)
        if not micro_part.isdigit():
            return None
        micro_val = float(f"0.{micro_part}")
    else:
        main_part = t

    parts = main_part.split(":")
    if len(parts) > 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None

    if len(nums) == 3:
        if nums[0] >= 24 or nums[1] >= 60 or nums[2] >= 60:
            return None
        return nums[0] * 3600 + nums[1] * 60 + nums[2] + micro_val
    elif len(nums) == 2:
        if nums[0] >= 60 or nums[1] >= 60:
            return None
        return nums[0] * 60 + nums[1] + micro_val
    elif len(nums) == 1:
        if nums[0] >= 60:
            return None
        return nums[0] + micro_val
    return None


async def set_edit_state(message: Message, bot: Bot):
    reply_msg = await message.reply(EDIT_SEPARATOR_MSG)
    EDIT_STATE[message.from_user.id] = {
        "voice": message.reply_to_message,
        "prompt_msg": reply_msg
    }


async def handle_pending_edit(message: Message, bot: Bot) -> bool:
    user_id = message.from_user.id
    if user_id not in EDIT_STATE:
        return False

    state = EDIT_STATE.pop(user_id)
    voice_msg = state["voice"]
    prompt_msg = state["prompt_msg"]
    text_val = message.text.strip()
    voice_duration = voice_msg.voice.duration if voice_msg.voice else 0

    clean_text = re.sub(r"[/\-]", " ", text_val)
    segments = [s for s in clean_text.split() if s]

    if len(segments) == 1:
        start_val = "0"
        end_val = segments[0].strip()
        e_val = _parse_time(end_val)
        if e_val is None:
            await message.reply(EDIT_SEPARATOR_MSG)
            return True
        if e_val > voice_duration:
            await message.reply(EDIT_END_TOO_LONG_MSG)
            return True
    elif len(segments) == 2:
        start_val, end_val = segments[0].strip(), segments[1].strip()
        s_val, e_val = _parse_time(start_val), _parse_time(end_val)
        if s_val is None or e_val is None:
            await message.reply(EDIT_SEPARATOR_MSG)
            return True
        if s_val >= e_val:
            await message.reply(EDIT_START_BIGGER_MSG)
            return True
        if e_val > voice_duration:
            await message.reply(EDIT_END_TOO_LONG_MSG)
            return True
    else:
        await message.reply(EDIT_SEPARATOR_MSG)
        return True

    chat_id = message.chat.id
    is_private = message.chat.type == "private"
    workdir = user_dir(chat_id, user_id, bot.id, is_private)

    in_path = os.path.join(workdir, f"{voice_msg.message_id}_in.ogg")
    out_path = os.path.join(workdir, f"{message.message_id}_out.ogg")

    try:
        voice_file = await bot.get_file(voice_msg.voice.file_id)
        await bot.download_file(voice_file.file_path, in_path)
        success = await trim_voice(in_path, out_path, start_val, end_val)
        if success:
            await message.reply_voice(FSInputFile(out_path))
            try:
                await prompt_msg.delete()
            except Exception:
                pass
        else:
            await message.reply(EDIT_FAIL_MSG)
    except Exception:
        await message.reply(EDIT_FAIL_MSG)
    finally:
        cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
    return True