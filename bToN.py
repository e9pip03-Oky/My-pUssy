import logging
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import (
    BUTTON_NAMES, MODE_VOICE, MODE_DEFAULT, MODE_LANG, MODE_NOTE,
    LANG_ENG, LANG_RUS, LANG_ENABLE, LANG_DISABLE, LANG_BACK
)

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
    n_style = "primary" if current_mode == "note" else "danger"
    l_style = "success" if lang_active else "danger"

    b1 = InlineKeyboardButton(
        text=MODE_VOICE, callback_data=f"toggle:voice:{owner_id}:{mode_key}", style=v_style
    )
    b2 = InlineKeyboardButton(
        text=MODE_NOTE, callback_data=f"toggle:note:{owner_id}:{mode_key}", style=n_style
    )
    b3 = InlineKeyboardButton(
        text=MODE_DEFAULT, callback_data=f"toggle:default:{owner_id}:{mode_key}", style=d_style
    )
    b4 = InlineKeyboardButton(
        text=MODE_LANG, callback_data=f"lang:{owner_id}:{mode_key}", style=l_style
    )
    return InlineKeyboardMarkup(inline_keyboard=[[b1, b2, b3], [b4]])


def build_lang_markup(lang_active: bool, current_code: str, owner_id: int, mode_key: str) -> InlineKeyboardMarkup:
    eng_style = "primary" if current_code == "en" else "danger"
    rus_style = "primary" if current_code == "ru" else "danger"
    
    btn_eng = InlineKeyboardButton(text=LANG_ENG, callback_data=f"setlang:en:{owner_id}:{mode_key}", style=eng_style)
    btn_rus = InlineKeyboardButton(text=LANG_RUS, callback_data=f"setlang:ru:{owner_id}:{mode_key}", style=rus_style)
    
    if lang_active:
        btn_toggle = InlineKeyboardButton(text=LANG_DISABLE, callback_data=f"togglelang:{owner_id}:{mode_key}", style="primary")
    else:
        btn_toggle = InlineKeyboardButton(text=LANG_ENABLE, callback_data=f"togglelang:{owner_id}:{mode_key}", style="danger")
        
    btn_back = InlineKeyboardButton(text=LANG_BACK, callback_data=f"back:{owner_id}:{mode_key}", style="success")
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_eng, btn_rus],
        [btn_toggle],
        [btn_back]
    ])