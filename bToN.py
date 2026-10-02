import os
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import Reply

OWNER_BUTTON_STYLES = ["danger", "success", "primary"]

_owner_index = 0
_name_index = 0
_style_index = 0


def get_mode_keyboard(current_mode: str = "normal") -> InlineKeyboardMarkup:
    voice_style = "success" if current_mode == "voice" else "danger"
    normal_style = "success" if current_mode == "normal" else "danger"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Reply.BUTTON_VOICE_TEXT,
                    callback_data="set_mode_voice",
                    style=voice_style
                ),
                InlineKeyboardButton(
                    text=Reply.BUTTON_NORMAL_TEXT,
                    callback_data="set_mode_normal",
                    style=normal_style
                ),
            ],
            [
                InlineKeyboardButton(
                    text=Reply.EDIT_GUIDE_BUTTON_TEXT,
                    callback_data="show_edit_guide",
                    style="primary"
                )
            ]
        ]
    )
    return keyboard


def get_owner_keyboard() -> InlineKeyboardMarkup:
    global _owner_index, _name_index, _style_index

    takeoff_env = os.getenv("boT_TAkeoFF", "")
    owner_ids = [cid.strip() for cid in takeoff_env.split("/") if cid.strip()]

    if not owner_ids:
        return None

    current_id = owner_ids[_owner_index % len(owner_ids)]
    current_name = Reply.OWNER_BUTTON_NAMES[_name_index % len(Reply.OWNER_BUTTON_NAMES)]
    current_style = OWNER_BUTTON_STYLES[_style_index % len(OWNER_BUTTON_STYLES)]

    _owner_index = (_owner_index + 1) % len(owner_ids)
    _name_index = (_name_index + 1) % len(Reply.OWNER_BUTTON_NAMES)
    _style_index = (_style_index + 1) % len(OWNER_BUTTON_STYLES)

    button_url = f"tg://user?id={current_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=current_name,
                    url=button_url,
                    style=current_style
                )
            ]
        ]
    )
    return keyboard
