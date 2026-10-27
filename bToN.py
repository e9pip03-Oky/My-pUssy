import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import BUTTON_NAMES, MODE_VOICE, MODE_DEFAULT, MODE_LANG

log = logging.getLogger("voicebot")
BUTTON_STYLES = ("primary", "success", "danger")


def parse_ids(raw: str) -> list[int]:
    return [int(p.strip()) for p in raw.split("/") if p.strip().isdigit()]


def build_buttons(ids: list[int]) -> list[tuple[int, str, str]]:
    result = []
    seen_ids = set()
    for index, user_id in enumerate([uid for uid in ids if uid not in seen_ids and not seen_ids.add(uid)]):
        name = BUTTON_NAMES[index % len(BUTTON_NAMES)]
        style = BUTTON_STYLES[index % len(BUTTON_STYLES)]
        result.append((user_id, name, style))
    return result


def build_markup(name: str, user_id: int, style: str) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(text=name, url=f"tg://user?id={user_id}", style=style)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_mode_markup(current_mode: str, lang_active: bool, owner_id: int, mode_key: str) -> InlineKeyboardMarkup:
    voice_style = "primary" if current_mode == "voice" else "danger"
    default_style = "primary" if current_mode == "default" else "danger"
    lang_style = "success" if lang_active else "danger"
    
    btn_voice = InlineKeyboardButton(text=MODE_VOICE, callback_data=f"toggle:{owner_id}:{mode_key}", style=voice_style)
    btn_default = InlineKeyboardButton(text=MODE_DEFAULT, callback_data=f"toggle:{owner_id}:{mode_key}", style=default_style)
    btn_lang = InlineKeyboardButton(text=MODE_LANG, callback_data=f"lang:{owner_id}:{mode_key}", style=lang_style)
    
    return InlineKeyboardMarkup(inline_keyboard=[[btn_voice, btn_default], [btn_lang]])