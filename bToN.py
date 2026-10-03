import os
from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.enums import ButtonStyle

import Reply
import CAsh

_btn_rotation_index = 0

BTN_COLORS = [
    ButtonStyle.SUCCESS,
    ButtonStyle.DANGER,
    ButtonStyle.PRIMARY
]


def _parse_takeoff_env() -> list[tuple[str, str]]:
    raw_env = os.getenv("boT_TAkeoFF", "")
    if not raw_env:
        return []
    items = []
    pairs = raw_env.split(",")
    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split(":", 1)
        if len(parts) == 2:
            url = parts[0].strip()
            user_id = parts[1].strip()
            if url and user_id:
                items.append((url, user_id))
    return items


def get_next_takeoff_button() -> Optional[InlineKeyboardMarkup]:
    global _btn_rotation_index
    items = _parse_takeoff_env()
    if not items:
        return None

    count = len(items)
    idx = _btn_rotation_index % count
    _btn_rotation_index += 1

    url, user_id = items[idx]
    label = Reply.BTN_NAMES[idx % len(Reply.BTN_NAMES)]
    color = BTN_COLORS[idx % len(BTN_COLORS)]

    button = InlineKeyboardButton(
        text=label,
        url=url,
        style=color
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def get_edit_keyboard(chat_id: int, thread_id: int) -> InlineKeyboardMarkup:
    current_mode = await CAsh.get_chat_mode(chat_id, thread_id)
    
    if current_mode == "voice":
        voice_style = ButtonStyle.SUCCESS
        normal_style = ButtonStyle.DANGER
    else:
        voice_style = ButtonStyle.DANGER
        normal_style = ButtonStyle.SUCCESS

    btn_voice = InlineKeyboardButton(
        text=Reply.BTN_VOICE,
        callback_data="set_mode:voice",
        style=voice_style
    )
    btn_normal = InlineKeyboardButton(
        text=Reply.BTN_NORMAL,
        callback_data="set_mode:normal",
        style=normal_style
    )

    return InlineKeyboardMarkup(inline_keyboard=[[btn_voice, btn_normal]])


async def is_user_allowed_to_edit(message: Message) -> bool:
    if message.chat.type == "private":
        return True

    member = await message.chat.get_member(message.from_user.id)
    return member.status in ("creator", "administrator")


async def is_user_admin(callback_query: CallbackQuery) -> bool:
    if callback_query.message.chat.type == "private":
        return True

    user_id = callback_query.from_user.id
    chat = callback_query.message.chat

    member = await chat.get_member(user_id)
    return member.status in ("creator", "administrator")
