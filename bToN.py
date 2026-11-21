import logging
from typing import Final

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import (
    ANIMATION,
    ANIMATION_CROP_DOWN,
    ANIMATION_CROP_UP,
    ANIMATION_DIMENSIONS,
    ANIMATION_DIM_9_16,
    ANIMATION_DIM_16_9,
    ANIMATION_DOUBLE_ROTATE,
    ANIMATION_FLIP,
    ANIMATION_HORIZONTAL,
    ANIMATION_LANDSCAPE,
    ANIMATION_MUTE,
    ANIMATION_PORTRAIT,
    BUTTON_NAMES,
    DEFAULT,
    DEFAULT_SEND_DOCUMENT,
    DEFAULT_SEND_VIDEO,
    DISABLE,
    ENABLE,
    LANG_BACK,
    LANG_ENG,
    LANG_RUS,
    MODE_LANG,
    NOTE,
    NOTIF_CLOSE,
    NOTIF_OPEN,
    VOICE,
)

log = logging.getLogger("voicebot")

BUTTON_STYLES: Final = ("primary", "success", "danger")
STYLE_ON: Final = "primary"
STYLE_OFF: Final = "danger"
STYLE_BACK: Final = "success"


def parse_ids(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split("/") if part.strip().isdigit()]


def build_buttons(ids: list[int]) -> list[tuple[int, str, str]]:
    seen: set[int] = set()
    result: list[tuple[int, str, str]] = []
    for index, user_id in enumerate(ids):
        if user_id in seen:
            continue
        seen.add(user_id)
        result.append(
            (
                user_id,
                BUTTON_NAMES[index % len(BUTTON_NAMES)],
                BUTTON_STYLES[index % len(BUTTON_STYLES)],
            )
        )
    return result


def build_markup(name: str, user_id: int, style: str) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=name, url=f"tg://user?id={user_id}", style=style
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_specific_markup(
    index: int, boot_notice: str
) -> InlineKeyboardMarkup | None:
    ids = parse_ids(boot_notice)
    if not ids:
        return None
    unique_ids = list(dict.fromkeys(ids))
    user_id = unique_ids[index % len(unique_ids)]
    return build_markup(
        BUTTON_NAMES[index % len(BUTTON_NAMES)],
        user_id,
        BUTTON_STYLES[index % len(BUTTON_STYLES)],
    )


def _style(active: bool) -> str:
    return STYLE_ON if active else STYLE_OFF


def _btn(label: str, data: str, style: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=data, style=style)


def _toggle(label: str, data: str, active: bool) -> InlineKeyboardButton:
    return _btn(label, data, _style(active))


def _back(action: str, owner_id: int, mode_key: str) -> InlineKeyboardButton:
    return _btn(LANG_BACK, f"back:{action}|{owner_id}|{mode_key}", STYLE_BACK)


def _state_toggle(
    action: str, owner_id: int, mode_key: str, active: bool
) -> InlineKeyboardButton:
    label = DISABLE if active else ENABLE
    return _toggle(label, f"toggle_state:{action}|{owner_id}|{mode_key}", active)


def _setting_btn(
    label: str,
    prefix: str,
    field: str,
    owner_id: int,
    mode_key: str,
    active: bool,
) -> InlineKeyboardButton:
    return _toggle(label, f"{prefix}:{field}|{owner_id}|{mode_key}", active)


def build_mode_markup(
    current_mode: str,
    lang_active: bool,
    owner_id: int,
    mode_key: str,
    notif_active: bool = False,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    ANIMATION,
                    f"animation_menu|{owner_id}|{mode_key}",
                    _style(current_mode == "animation"),
                )
            ],
            [
                _toggle(
                    VOICE,
                    f"toggle:voice|{owner_id}|{mode_key}",
                    current_mode == "voice",
                ),
                _btn(
                    DEFAULT,
                    f"default_menu|{owner_id}|{mode_key}",
                    _style(current_mode == "default"),
                ),
                _btn(
                    NOTE,
                    f"note_menu|{owner_id}|{mode_key}",
                    _style(current_mode == "note"),
                ),
            ],
            [
                _btn(
                    MODE_LANG,
                    f"lang|{owner_id}|{mode_key}",
                    STYLE_BACK if lang_active else STYLE_OFF,
                ),
                _btn(
                    NOTIF_CLOSE if notif_active else NOTIF_OPEN,
                    f"toggle_notif|{owner_id}|{mode_key}",
                    STYLE_BACK if notif_active else STYLE_OFF,
                ),
            ],
        ]
    )


def build_default_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    send_as = settings.get("send_as", "document")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_state_toggle("default", owner_id, mode_key, is_active)],
            [
                _toggle(
                    DEFAULT_SEND_DOCUMENT,
                    f"default_toggle:document|{owner_id}|{mode_key}",
                    send_as == "document",
                ),
                _toggle(
                    DEFAULT_SEND_VIDEO,
                    f"default_toggle:video|{owner_id}|{mode_key}",
                    send_as == "video",
                ),
            ],
            [_back("default", owner_id, mode_key)],
        ]
    )


def build_animation_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    crop_ratio = settings.get("crop_ratio", "none")

    def setting(label: str, field: str) -> InlineKeyboardButton:
        return _setting_btn(
            label,
            "animation_set",
            field,
            owner_id,
            mode_key,
            settings.get(field, False),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    ANIMATION_DIMENSIONS,
                    f"dimensions_menu|{owner_id}|{mode_key}",
                    STYLE_BACK if crop_ratio == "none" else STYLE_ON,
                )
            ],
            [
                setting(ANIMATION_PORTRAIT, "portrait"),
                _state_toggle("animation", owner_id, mode_key, is_active),
                setting(ANIMATION_LANDSCAPE, "landscape"),
            ],
            [
                setting(ANIMATION_DOUBLE_ROTATE, "double_rotate"),
                setting(ANIMATION_FLIP, "flip_left"),
            ],
            [_back("animation", owner_id, mode_key)],
        ]
    )


def build_note_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    def setting(label: str, field: str, active: bool) -> InlineKeyboardButton:
        return _setting_btn(label, "note_set", field, owner_id, mode_key, active)

    crop_align = settings.get("crop_align", "center")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                setting(
                    ANIMATION_DOUBLE_ROTATE,
                    "double_rotate",
                    settings.get("double_rotate", False),
                ),
                setting(ANIMATION_MUTE, "muted", settings.get("muted", False)),
            ],
            [
                setting(
                    ANIMATION_PORTRAIT,
                    "portrait",
                    settings.get("portrait", False),
                ),
                _state_toggle("note", owner_id, mode_key, is_active),
                setting(
                    ANIMATION_LANDSCAPE,
                    "landscape",
                    settings.get("landscape", False),
                ),
            ],
            [
                setting(
                    ANIMATION_CROP_DOWN, "crop_down", crop_align == "bottom"
                ),
                setting(
                    ANIMATION_FLIP,
                    "flip_left",
                    settings.get("flip_left", False),
                ),
                setting(ANIMATION_CROP_UP, "crop_up", crop_align == "top"),
            ],
            [
                setting(
                    ANIMATION_HORIZONTAL,
                    "horizontal",
                    settings.get("horizontal", False),
                )
            ],
            [_back("note", owner_id, mode_key)],
        ]
    )


def build_dimensions_markup(
    settings: dict, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    crop_ratio = settings.get("crop_ratio", "none")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _toggle(
                    ANIMATION_DIM_9_16,
                    f"dim_ratio:9_16|{owner_id}|{mode_key}",
                    crop_ratio == "9:16",
                ),
                _toggle(
                    ANIMATION_DIM_16_9,
                    f"dim_ratio:16_9|{owner_id}|{mode_key}",
                    crop_ratio == "16:9",
                ),
            ],
            [
                _btn(
                    LANG_BACK,
                    f"back_to_animation|{owner_id}|{mode_key}",
                    STYLE_BACK,
                )
            ],
        ]
    )


def build_lang_markup(
    lang_active: bool, current_code: str, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_state_toggle("lang", owner_id, mode_key, lang_active)],
            [
                _toggle(
                    LANG_ENG,
                    f"setlang:en|{owner_id}|{mode_key}",
                    current_code == "en",
                ),
                _toggle(
                    LANG_RUS,
                    f"setlang:ru|{owner_id}|{mode_key}",
                    current_code == "ru",
                ),
            ],
            [
                _btn(
                    LANG_BACK,
                    f"back_to_default|{owner_id}|{mode_key}",
                    STYLE_BACK,
                )
            ],
        ]
    )
