import os
import re
import subprocess
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message, ReplyParameters

import Reply
import bToN


router = Router()


class EditStates(StatesGroup):
    waiting_for_time = State()


def parse_time_str(val):
    val = val.strip()

    if ":" in val:
        parts = val.split(":")

        if len(parts) != 2:
            return None

        m_str, s_str = parts[0], parts[1]

        if not m_str.isdigit() or not s_str.isdigit():
            return None

        return int(m_str) * 60 + int(s_str)

    if val.isdigit() and val.startswith("0"):
        return int(val)

    return None


def parse_trim_input(text):
    text = text.strip()

    if " / " in text:
        parts = text.split(" / ")
    elif " - " in text:
        parts = text.split(" - ")
    elif " " in text and not ("/" in text or "-" in text):
        parts = re.split(r"\s+", text)
    else:
        return None

    if len(parts) != 2:
        return None

    start_sec = parse_time_str(parts[0])
    end_sec = parse_time_str(parts[1])

    if start_sec is None or end_sec is None:
        return None

    return start_sec, end_sec


def trim_voice_file(input_path, output_path, start_sec, end_sec):
    ffmpeg_path = bToN.get_ffmpeg_path() or "ffmpeg"
    duration = end_sec - start_sec

    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        str(input_path),
        "-t",
        str(duration),
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(output_path),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@router.message(F.reply_to_message & F.reply_to_message.voice & (F.text == Reply.COMMAND_EDIT))
async def edit_command_handler(message: Message, bot: Bot, state: FSMContext):
    if message.chat.type in {"group", "supergroup"}:
        if not await bToN.is_bot_admin(bot, message.chat.id):
            return

    voice = message.reply_to_message.voice

    await state.update_data(
        file_id=voice.file_id,
        chat_id=message.chat.id,
    )

    await state.set_state(EditStates.waiting_for_time)

    await message.reply(
        Reply.EDIT_PROMPT_TEXT,
        reply_parameters=ReplyParameters(message_id=message.message_id),
    )


@router.message(EditStates.waiting_for_time, F.text)
async def process_time_handler(message: Message, bot: Bot, state: FSMContext):
    parsed = parse_trim_input(message.text)

    if parsed is None:
        return

    start_sec, end_sec = parsed

    if start_sec > end_sec:
        await message.reply(
            Reply.TRIM_START_GREATER,
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
        await state.clear()
        return

    data = await state.get_data()
    file_id = data.get("file_id")

    await state.clear()

    user_dir = bToN.download_directory(message.from_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    input_path = user_dir / f"input_{message.message_id}.ogg"
    output_path = user_dir / f"trimmed_{message.message_id}.ogg"

    try:
        tg_file = await bot.get_file(file_id)
        await bot.download_file(tg_file.file_path, destination=input_path)

        trim_voice_file(input_path, output_path, start_sec, end_sec)

        await bot.send_voice(
            chat_id=message.chat.id,
            voice=FSInputFile(output_path),
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
    finally:
        if input_path.exists():
            input_path.unlink()
        if output_path.exists():
            output_path.unlink()
