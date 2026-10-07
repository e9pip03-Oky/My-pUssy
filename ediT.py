import asyncio
import re
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, Message

import Reply
import bToN
from yTFMe import cut_voice


EDIT_STATES = {}


def _state_key(message):
    return (
        message.chat.id,
        message.from_user.id,
    )


def _set_state(
    message,
    voice_message,
    status_message,
):
    EDIT_STATES[_state_key(message)] = (
        voice_message,
        status_message,
    )


def _get_state(message):
    return EDIT_STATES.get(
        _state_key(message)
    )


def _clear_state(message):
    EDIT_STATES.pop(
        _state_key(message),
        None,
    )


async def _bot_is_admin(
    bot,
    message,
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

    return (
        member.status.value
        in bToN.ADMIN_STATUSES
    )


def _parse_time(value):
    if not value.isdigit():
        return None

    parts = value.split(":")

    if len(parts) == 1:
        return int(parts[0])

    if len(parts) == 2:
        first, second = map(
            int,
            parts,
        )

        if second >= 60:
            return None

        if first == 0:
            return second

        return first * 60 + second

    if len(parts) == 3:
        hours, minutes, seconds = map(
            int,
            parts,
        )

        if (
            minutes >= 60
            or seconds >= 60
        ):
            return None

        return (
            hours * 3600
            + minutes * 60
            + seconds
        )

    return None


def _split_duration(text):
    match = re.fullmatch(
        r"\s*(\S+)\s+/\s+(\S+)\s*",
        text,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    match = re.fullmatch(
        r"\s*(\S+)\s+-\s+(\S+)\s*",
        text,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    match = re.fullmatch(
        r"\s*(\S+)\s+(\S+)\s*",
        text,
    )

    if match:
        return (
            match.group(1),
            match.group(2),
        )

    return None


def _parse_duration(text):
    values = _split_duration(text)

    if values is None:
        return None

    start = _parse_time(values[0])
    end = _parse_time(values[1])

    if start is None or end is None:
        return None

    return start, end


async def _download_voice(
    bot,
    voice_message,
    directory,
):
    directory = Path(directory)

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = directory / (
        f"{voice_message.message_id}.ogg"
    )

    await bot.download(
        voice_message.voice.file_id,
        destination=path,
    )

    return path


async def _delete_status(
    status_message,
):
    try:
        await status_message.delete()
    except Exception:
        pass


async def start_edit(
    bot,
    message,
):
    if not await _bot_is_admin(
        bot,
        message,
    ):
        return

    voice_message = (
        message.reply_to_message
    )

    if (
        voice_message is None
        or voice_message.voice is None
    ):
        return

    status_message = await message.reply(
        Reply.EDIT_WAITING
    )

    _set_state(
        message,
        voice_message,
        status_message,
    )


async def handle_duration(
    bot,
    message,
):
    state = _get_state(message)

    if state is None:
        return False

    duration = _parse_duration(
        message.text.strip()
    )

    if duration is None:
        await message.reply(
            Reply.EDIT_WAITING
        )
        return True

    start, end = duration

    if start > end:
        await message.reply(
            Reply.EDIT_REJECTED
        )
        return True

    voice_message, status_message = state

    if voice_message.voice is None:
        await message.reply(
            Reply.EDIT_ERROR
        )
        _clear_state(message)
        return True

    voice_duration = (
        voice_message.voice.duration
    )

    if (
        start >= voice_duration
        or end > voice_duration
        or start == end
    ):
        await message.reply(
            Reply.EDIT_ERROR
        )
        _clear_state(message)
        return True

    input_path = None
    output_path = None

    try:
        directory = (
            bToN.download_directory(
                message.from_user.id
            )
        )

        input_path = await _download_voice(
            bot,
            voice_message,
            directory,
        )

        output_path = input_path.with_name(
            f"{input_path.stem}.cut.ogg"
        )

        await cut_voice(
            input_path,
            output_path,
            start,
            end,
        )

        await _delete_status(
            status_message
        )

        await message.reply_voice(
            FSInputFile(output_path)
        )

    except Exception:
        await message.reply(
            Reply.EDIT_ERROR
        )

    finally:
        _clear_state(message)

        for path in (
            input_path,
            output_path,
        ):
            if path is not None:
                try:
                    path.unlink(
                        missing_ok=True
                    )
                except Exception:
                    pass

    return True