import re
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ButtonStyle
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import NAMe
import Reply
import bToN
from yTFMe import cut_voice


@dataclass
class EditState:
    voice_message: object


edit_states: dict[int, EditState] = {}

EDIT_INFO_CALLBACK = "edit_info_alert"

TIME_PATTERN = re.compile(
    r"^(?:\d+|\d+:\d{1,2}|\d+\.\d{1,2}(?::\d{1,2})?)$"
)

SEPARATOR_PATTERN = re.compile(
    r"^(?P<left>.+?)\s+(?:/|-)\s+(?P<right>.+)$"
)


def _parse_time(value):
    value = value.strip()

    if not TIME_PATTERN.fullmatch(value):
        return None

    if ":" in value:
        parts = value.split(":")

        if len(parts) == 2:
            minutes, seconds = map(int, parts)

            if minutes < 0 or minutes >= 60:
                return None

            if seconds < 0 or seconds >= 60:
                return None

            return minutes * 60 + seconds

        if len(parts) == 2:
            return None

        hours_minutes, seconds = parts

        if "." not in hours_minutes:
            return None

        hours, minutes = map(
            int,
            hours_minutes.split("."),
        )
        seconds = int(seconds)

        if hours < 0 or hours > 24:
            return None

        if minutes < 0 or minutes >= 60:
            return None

        if seconds < 0 or seconds >= 60:
            return None

        if hours == 24 and (
            minutes != 0
            or seconds != 0
        ):
            return None

        return (
            hours * 3600
            + minutes * 60
            + seconds
        )

    if "." in value:
        hours, minutes = map(
            int,
            value.split("."),
        )

        if hours < 0 or hours > 24:
            return None

        if minutes < 0 or minutes >= 60:
            return None

        if hours == 24 and minutes != 0:
            return None

        return hours * 3600 + minutes

    return int(value)


def parse_range(text):
    text = text.strip()

    match = SEPARATOR_PATTERN.fullmatch(text)

    if match:
        start_text = match.group("left")
        end_text = match.group("right")
    else:
        parts = text.split()

        if len(parts) != 2:
            return None, False

        start_text, end_text = parts

    start = _parse_time(start_text)
    end = _parse_time(end_text)

    if start is None or end is None:
        return None, False

    if start >= end:
        return None, True

    return (start, end), False


def start(user_id, voice_message):
    edit_states[user_id] = EditState(
        voice_message=voice_message
    )


def is_active(user_id):
    return user_id in edit_states


def clear(user_id):
    edit_states.pop(user_id, None)


def _edit_info_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Reply.EDIT_INFO_BUTTON,
                    callback_data=EDIT_INFO_CALLBACK,
                    style=ButtonStyle.PRIMARY,
                )
            ]
        ]
    )


async def send_edit_prompt(message: Message):
    await message.reply(
        Reply.EDIT_INFO_TEXT,
        reply_markup=_edit_info_keyboard(),
    )


async def handle_info_callback(callback: CallbackQuery):
    await callback.answer(
        Reply.EDIT_INFO_ALERT,
        show_alert=True,
    )


async def process(
    bot: Bot,
    message: Message,
):
    user_id = message.from_user.id

    state = edit_states.get(user_id)

    if state is None:
        return False

    parsed_range, start_greater = parse_range(
        message.text or ""
    )

    if start_greater:
        await message.reply(
            Reply.EDIT_START_GREATER
        )
        return True

    if parsed_range is None:
        await send_edit_prompt(message)
        return True

    start_time, end_time = parsed_range

    clear(user_id)

    directory = (
        Path(bToN.DOWNLOADS_DIR)
        / "edit"
        / str(user_id)
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    source = directory / (
        f"{state.voice_message.message_id}.ogg"
    )

    output = await bot.download(
        state.voice_message.voice.file_id,
        destination=source,
    )

    if output is None:
        return True

    try:
        edited = await cut_voice(
            source,
            start_time,
            end_time,
        )

        await NAMe.send_edited_voice(
            bot,
            state.voice_message,
            edited,
        )
    finally:
        for path in (
            source,
            output,
        ):
            if isinstance(path, Path):
                path.unlink(
                    missing_ok=True
                )

    return True
