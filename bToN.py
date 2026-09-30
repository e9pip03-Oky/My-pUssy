from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import DEVELOPER_BUTTON_NAMES, NORMAL_BUTTON, VOICE_BUTTON

DEVELOPER_NAMES = DEVELOPER_BUTTON_NAMES
DEVELOPER_STYLES = ("danger", "success", "primary")


def developer_button(developer_id, name_index, style_index):
    return InlineKeyboardButton(
        text=DEVELOPER_NAMES[name_index],
        style=DEVELOPER_STYLES[style_index],
        url=f"tg://user?id={developer_id}",
    )


def mode_keyboard(mode, developer_id=None, name_index=0, style_index=0):
    buttons = [
        InlineKeyboardButton(
            text=VOICE_BUTTON,
            style="success" if mode == "voice" else "danger",
            callback_data="mode:voice",
        ),
        InlineKeyboardButton(
            text=NORMAL_BUTTON,
            style="success" if mode == "normal" else "danger",
            callback_data="mode:normal",
        ),
    ]

    rows = [buttons]

    if developer_id is not None:
        rows.append([
            developer_button(
                developer_id,
                name_index,
                style_index,
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def developer_keyboard(developer_id, name_index, style_index):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            developer_button(
                developer_id,
                name_index,
                style_index,
            )
        ]]
    )
