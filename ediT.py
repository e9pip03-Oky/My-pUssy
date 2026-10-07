import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, Message

import Reply
import bToN


TIME_PATTERN = (
    r"(?:\d+|\d+:\d{1,2}|\d+:\d{1,2}:\d{1,2})"
)

RANGE_PATTERN = re.compile(
    rf"^\s*({TIME_PATTERN})\s+(?:/|-)\s+"
    rf"({TIME_PATTERN})\s*$|"
    rf"^\s*({TIME_PATTERN})\s+"
    rf"({TIME_PATTERN})\s*$"
)


@dataclass
class EditState:
    voice_message: Message
    status_message: Message


edit_states: dict[
    tuple[int, int, int | None],
    EditState,
] = {}


def _state_key(message):
    return (
        message.chat.id,
        message.from_user.id,
        message.message_thread_id,
    )


async def _bot_is_admin(
    bot: Bot,
    message: Message,
):
    if message.chat.type == "private":
        return True

    if message.chat.type not in {
        "group",
        "supergroup",
    }:
        return False

    member = await bot.get_chat_member(
        message.chat.id,
        bot.id,
    )

    return member.status.value in {
        "administrator",
        "creator",
    }


def _parse_time(value):
    parts = value.split(":")

    if len(parts) == 1:
        return int(parts[0])

    if len(parts) == 2:
        minutes, seconds = map(int, parts)

        if seconds >= 60:
            raise ValueError

        return minutes * 60 + seconds

    if len(parts) == 3:
        hours, minutes, seconds = map(int, parts)

        if minutes >= 60 or seconds >= 60:
            raise ValueError

        return (
            hours * 3600
            + minutes * 60
            + seconds
        )

    raise ValueError


def parse_range(text):
    match = RANGE_PATTERN.fullmatch(text)

    if match is None:
        return None

    first = match.group(1) or match.group(3)
    second = match.group(2) or match.group(4)

    try:
        start = _parse_time(first)
        end = _parse_time(second)
    except ValueError:
        return None

    return start, end


def _state(message):
    return edit_states.get(
        _state_key(message)
    )


async def _send_edit_prompt(message):
    return await message.reply(
        Reply.EDIT_PROMPT
    )


async def _enter_edit_mode(
    bot: Bot,
    message: Message,
):
    if not await _bot_is_admin(bot, message):
        return False

    replied_message = message.reply_to_message

    if replied_message is None:
        return True

    if replied_message.voice is None:
        return True

    key = _state_key(message)

    previous = edit_states.pop(key, None)

    if previous is not None:
        try:
            await previous.status_message.delete()
        except Exception:
            pass

    status_message = await _send_edit_prompt(
        message
    )

    edit_states[key] = EditState(
        voice_message=replied_message,
        status_message=status_message,
    )

    return True


async def _download_voice(
    bot: Bot,
    voice_message: Message,
    directory: Path,
):
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    input_path = (
        directory
        / f"edit_{voice_message.message_id}.ogg"
    )

    await bot.download(
        voice_message.voice.file_id,
        destination=input_path,
    )

    return input_path


def _cut_voice_sync(
    input_path,
    output_path,
    start,
    end,
):
    duration = end - start

    ffmpeg_path = (
        bToN.get_ffmpeg_path()
        or "ffmpeg"
    )

    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        str(start),
        "-i",
        str(input_path),
        "-t",
        str(duration),
        "-c",
        "copy",
        str(output_path),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return output_path


async def _cut_voice(
    input_path,
    output_path,
    start,
    end,
):
    return await asyncio.to_thread(
        _cut_voice_sync,
        input_path,
        output_path,
        start,
        end,
    )


async def _remove_file(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


async def _send_cut_voice(
    message,
    output_path,
):
    await message.reply_voice(
        voice=FSInputFile(output_path)
    )


async def _process_edit(
    bot: Bot,
    message: Message,
    state: EditState,
    start: int,
    end: int,
):
    if start > end:
        await message.reply(
            Reply.EDIT_START_AFTER_END
        )
        return

    directory = bToN.download_directory(
        message.from_user.id
    )

    input_path = None
    output_path = (
        Path(directory)
        / f"edit_{message.message_id}.ogg"
    )

    try:
        input_path = await _download_voice(
            bot,
            state.voice_message,
            Path(directory),
        )

        await _cut_voice(
            input_path,
            output_path,
            start,
            end,
        )

        try:
            await state.status_message.delete()
        except Exception:
            pass

        edit_states.pop(
            _state_key(message),
            None,
        )

        await _send_cut_voice(
            message,
            output_path,
        )

    except Exception:
        await message.reply(
            Reply.EDIT_FAILED
        )

    finally:
        if input_path is not None:
            await _remove_file(input_path)

        await _remove_file(output_path)


async def handle(
    bot: Bot,
    message: Message,
):
    text = message.text.strip()

    if text == Reply.COMMAND_EDIT:
        return await _enter_edit_mode(
            bot,
            message,
        )

    state = _state(message)

    if state is None:
        return False

    parsed = parse_range(text)

    if parsed is None:
        try:
            await state.status_message.edit_text(
                Reply.EDIT_PROMPT
            )
        except Exception:
            pass

        return True

    start, end = parsed

    await _process_edit(
        bot,
        message,
        state,
        start,
        end,
    )

    return True