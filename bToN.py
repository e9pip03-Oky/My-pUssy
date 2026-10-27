import logging
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import BUTTON_NAMES, MODE_VOICE, MODE_DEFAULT, MODE_LANG

log = logging.getLogger("voicebot")
BUTTON_STYLES = ("primary", "success", "danger")


def parse_ids(raw: str) -> list[int]:
    return [int(p.strip()) for p in raw.split("/") if p.strip().isdigit()]


def build_buttons(ids: list[int]) -> list[tuple[int, str, str]]:
    result = []
    seen = set()
    for i, uid in enumerate([u for u in ids if u not in seen and not seen.add(u)]):
        result.append(
            (
                uid,
                BUTTON_NAMES[i % len(BUTTON_NAMES)],
                BUTTON_STYLES[i % len(BUTTON_STYLES)],
            )
        )
    return result


def build_markup(name: str, user_id: int, style: str) -> InlineKeyboardMarkup:
    btn = InlineKeyboardButton(text=name, url=f"tg://user?id={user_id}", style=style)
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def build_specific_markup(index: int) -> InlineKeyboardMarkup | None:
    ids = parse_ids(os.environ.get("boT_NoTice", ""))
    if not ids:
        return None
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return None
    uid = unique_ids[index % len(unique_ids)]
    name = BUTTON_NAMES[index % len(BUTTON_NAMES)]
    style = BUTTON_STYLES[index % len(BUTTON_STYLES)]
    return build_markup(name, uid, style)


def build_mode_markup(
    current_mode: str, lang_active: bool, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    v_style = "primary" if current_mode == "voice" else "danger"
    d_style = "primary" if current_mode == "default" else "danger"
    l_style = "success" if lang_active else "danger"

    b1 = InlineKeyboardButton(
        text=MODE_VOICE, callback_data=f"toggle:{owner_id}:{mode_key}", style=v_style
    )
    b2 = InlineKeyboardButton(
        text=MODE_DEFAULT, callback_data=f"toggle:{owner_id}:{mode_key}", style=d_style
    )
    b3 = InlineKeyboardButton(
        text=MODE_LANG, callback_data=f"lang:{owner_id}:{mode_key}", style=l_style
    )
    return InlineKeyboardMarkup(inline_keyboard=[[b1, b2], [b3]])