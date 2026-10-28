import logging
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import (
    BUTTON_NAMES,
    LANG_BACK,
    LANG_DISABLE,
    LANG_ENABLE,
    LANG_ENG,
    LANG_RUS,
    MODE_DEFAULT,
    MODE_LANG,
    MODE_NOTE,
    MODE_STICKER,
    MODE_VOICE,
    STICKER_DISABLE,
    STICKER_ENABLE,
    STICKER_FLIP_LEFT,
    STICKER_FLIP_RIGHT,
    STICKER_LANDSCAPE,
    STICKER_PORTRAIT,
)

log = logging.getLogger("voicebot")
BUTTON_STYLES = ("primary", "success", "danger")


def parse_ids(raw: str) -> list[int]:
    return [int(p.strip()) for p in raw.split("/") if p.strip().isdigit()]


def build_buttons(ids: list[int]) -> list[tuple[int, str, str]]:
    result = []
    seen = set()
    for index, user_id in enumerate([u for u in ids if u not in seen and not seen.add(u)]):
        result.append(
            (
                user_id,
                BUTTON_NAMES[index % len(BUTTON_NAMES)],
                BUTTON_STYLES[index % len(BUTTON_STYLES)],
            )
        )
    return result


def build_markup(name: str, user_id: int, style: str) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(text=name, url=f"tg://user?id={user_id}", style=style)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_specific_markup(index: int) -> InlineKeyboardMarkup | None:
    ids = parse_ids(os.environ.get("boT_NoTice", ""))
    if not ids:
        return None
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return None
    user_id = unique_ids[index % len(unique_ids)]
    name = BUTTON_NAMES[index % len(BUTTON_NAMES)]
    style = BUTTON_STYLES[index % len(BUTTON_STYLES)]
    return build_markup(name, user_id, style)


def build_mode_markup(
    current_mode: str,
    lang_active: bool,
    owner_id: int,
    mode_key: str,
    sticker_enabled: bool = False,
) -> InlineKeyboardMarkup:
    # إذا كان الستيكر مفعلاً، فهو الوضع الحصري. وإلا نستخدم الوضع الحالي.
    effective_mode = "sticker" if sticker_enabled else current_mode

    voice_style = "primary" if effective_mode == "voice" else "danger"
    default_style = "primary" if effective_mode == "default" else "danger"
    sticker_style = "primary" if effective_mode == "sticker" else "danger"
    note_style = "primary" if effective_mode == "note" else "danger"
    lang_style = "success" if lang_active else "danger"

    btn_voice = InlineKeyboardButton(
        text=MODE_VOICE,
        callback_data=f"toggle:voice:{owner_id}:{mode_key}",
        style=voice_style,
    )
    btn_default = InlineKeyboardButton(
        text=MODE_DEFAULT,
        callback_data=f"toggle:default:{owner_id}:{mode_key}",
        style=default_style,
    )
    btn_sticker = InlineKeyboardButton(
        text=MODE_STICKER,
        callback_data=f"sticker_menu:{owner_id}:{mode_key}",
        style=sticker_style,
    )
    btn_note = InlineKeyboardButton(
        text=MODE_NOTE,
        callback_data=f"toggle:note:{owner_id}:{mode_key}",
        style=note_style,
    )
    btn_lang = InlineKeyboardButton(
        text=MODE_LANG,
        callback_data=f"lang:{owner_id}:{mode_key}",
        style=lang_style,
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_sticker],
            [btn_voice, btn_note, btn_default],
            [btn_lang],
        ]
    )


def build_sticker_markup(
    settings: dict, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    landscape_style = "primary" if settings["landscape"] else "danger"
    portrait_style = "primary" if settings["portrait"] else "danger"
    flip_left_style = "primary" if settings["flip_left"] else "danger"
    flip_right_style = "primary" if settings["flip_right"] else "danger"

    btn_landscape = InlineKeyboardButton(
        text=STICKER_LANDSCAPE,
        callback_data=f"sticker_set:landscape:{owner_id}:{mode_key}",
        style=landscape_style,
    )
    btn_portrait = InlineKeyboardButton(
        text=STICKER_PORTRAIT,
        callback_data=f"sticker_set:portrait:{owner_id}:{mode_key}",
        style=portrait_style,
    )
    btn_flip_left = InlineKeyboardButton(
        text=STICKER_FLIP_LEFT,
        callback_data=f"sticker_set:flip_left:{owner_id}:{mode_key}",
        style=flip_left_style,
    )
    btn_flip_right = InlineKeyboardButton(
        text=STICKER_FLIP_RIGHT,
        callback_data=f"sticker_set:flip_right:{owner_id}:{mode_key}",
        style=flip_right_style,
    )

    if settings["enabled"]:
        btn_toggle = InlineKeyboardButton(
            text=STICKER_DISABLE,
            callback_data=f"toggle_state:sticker:{owner_id}:{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=STICKER_ENABLE,
            callback_data=f"toggle_state:sticker:{owner_id}:{mode_key}",
            style="danger",
        )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:sticker:{owner_id}:{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_landscape, btn_portrait],
            [btn_flip_left, btn_flip_right],
            [btn_toggle],
            [btn_back],
        ]
    )


def build_lang_markup(
    lang_active: bool, current_code: str, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    eng_style = "primary" if current_code == "en" else "danger"
    rus_style = "primary" if current_code == "ru" else "danger"

    btn_eng = InlineKeyboardButton(
        text=LANG_ENG,
        callback_data=f"setlang:en:{owner_id}:{mode_key}",
        style=eng_style,
    )
    btn_rus = InlineKeyboardButton(
        text=LANG_RUS,
        callback_data=f"setlang:ru:{owner_id}:{mode_key}",
        style=rus_style,
    )

    if lang_active:
        btn_toggle = InlineKeyboardButton(
            text=LANG_DISABLE,
            callback_data=f"toggle_state:lang:{owner_id}:{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=LANG_ENABLE,
            callback_data=f"toggle_state:lang:{owner_id}:{mode_key}",
            style="danger",
        )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:lang:{owner_id}:{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[[btn_eng, btn_rus], [btn_toggle], [btn_back]]
    )