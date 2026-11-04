import logging
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Reply import (
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
    STICKER,
    STICKER_CROP_DOWN,
    STICKER_CROP_UP,
    STICKER_DIMENSIONS,
    STICKER_DIM_9_16,
    STICKER_DIM_16_9,
    STICKER_DOUBLE_ROTATE,
    STICKER_FLIP,
    STICKER_LANDSCAPE,
    STICKER_MUTE,
    STICKER_PORTRAIT,
    VOICE,
)

log = logging.getLogger("voicebot")
BUTTON_STYLES = ("primary", "success", "danger")


def parse_ids(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split("/") if part.strip().isdigit()]


def build_buttons(ids: list[int]) -> list[tuple[int, str, str]]:
    result = []
    seen: set[int] = set()
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
    button = InlineKeyboardButton(text=name, url=f"tg://user?id={user_id}", style=style)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_specific_markup(index: int) -> InlineKeyboardMarkup | None:
    ids = parse_ids(os.environ.get("boT_NoTice", ""))
    if not ids:
        return None
    unique_ids = list(dict.fromkeys(ids))
    user_id = unique_ids[index % len(unique_ids)]
    name = BUTTON_NAMES[index % len(BUTTON_NAMES)]
    style = BUTTON_STYLES[index % len(BUTTON_STYLES)]
    return build_markup(name, user_id, style)


def build_mode_markup(
    current_mode: str, lang_active: bool, owner_id: int, mode_key: str
) -> InlineKeyboardMarkup:
    voice_style = "primary" if current_mode == "voice" else "danger"
    default_style = "primary" if current_mode == "default" else "danger"
    sticker_style = "primary" if current_mode == "sticker" else "danger"
    note_style = "primary" if current_mode == "note" else "danger"
    lang_style = "success" if lang_active else "danger"

    btn_voice = InlineKeyboardButton(
        text=VOICE,
        callback_data=f"toggle:voice|{owner_id}|{mode_key}",
        style=voice_style,
    )
    btn_default = InlineKeyboardButton(
        text=DEFAULT,
        callback_data=f"default_menu|{owner_id}|{mode_key}",
        style=default_style,
    )
    btn_sticker = InlineKeyboardButton(
        text=STICKER,
        callback_data=f"sticker_menu|{owner_id}|{mode_key}",
        style=sticker_style,
    )
    btn_note = InlineKeyboardButton(
        text=NOTE,
        callback_data=f"note_menu|{owner_id}|{mode_key}",
        style=note_style,
    )
    btn_lang = InlineKeyboardButton(
        text=MODE_LANG,
        callback_data=f"lang|{owner_id}|{mode_key}",
        style=lang_style,
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_sticker],
            [btn_voice, btn_default, btn_note],
            [btn_lang],
        ]
    )


def build_settings_buttons(
    settings: dict,
    owner_id: int,
    mode_key: str,
    action_prefix: str,
    middle_button: InlineKeyboardButton | None = None,
) -> list[list[InlineKeyboardButton]]:
    landscape_style = "primary" if settings.get("landscape") else "danger"
    portrait_style = "primary" if settings.get("portrait") else "danger"
    flip_style = "primary" if settings.get("flip_left") else "danger"
    double_rotate_style = "primary" if settings.get("double_rotate") else "danger"

    btn_landscape = InlineKeyboardButton(
        text=STICKER_LANDSCAPE,
        callback_data=f"{action_prefix}:landscape|{owner_id}|{mode_key}",
        style=landscape_style,
    )
    btn_portrait = InlineKeyboardButton(
        text=STICKER_PORTRAIT,
        callback_data=f"{action_prefix}:portrait|{owner_id}|{mode_key}",
        style=portrait_style,
    )
    btn_double_rotate = InlineKeyboardButton(
        text=STICKER_DOUBLE_ROTATE,
        callback_data=f"{action_prefix}:double_rotate|{owner_id}|{mode_key}",
        style=double_rotate_style,
    )
    btn_flip = InlineKeyboardButton(
        text=STICKER_FLIP,
        callback_data=f"{action_prefix}:flip|{owner_id}|{mode_key}",
        style=flip_style,
    )

    row1 = [btn_portrait, btn_landscape]
    if middle_button:
        row1 = [btn_portrait, middle_button, btn_landscape]

    return [row1, [btn_double_rotate, btn_flip]]


def build_default_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    send_as = settings.get("send_as", "document")
    document_style = "primary" if send_as == "document" else "danger"
    video_style = "primary" if send_as == "video" else "danger"

    btn_document = InlineKeyboardButton(
        text=DEFAULT_SEND_DOCUMENT,
        callback_data=f"default_toggle:document|{owner_id}|{mode_key}",
        style=document_style,
    )
    btn_video = InlineKeyboardButton(
        text=DEFAULT_SEND_VIDEO,
        callback_data=f"default_toggle:video|{owner_id}|{mode_key}",
        style=video_style,
    )

    crop_ratio = settings.get("crop_ratio", "none")
    dimensions_style = "success" if crop_ratio == "none" else "primary"

    btn_dimensions = InlineKeyboardButton(
        text=STICKER_DIMENSIONS,
        callback_data=f"default_dimensions_menu|{owner_id}|{mode_key}",
        style=dimensions_style,
    )

    if is_active:
        btn_toggle = InlineKeyboardButton(
            text=DISABLE,
            callback_data=f"toggle_state:default|{owner_id}|{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=ENABLE,
            callback_data=f"toggle_state:default|{owner_id}|{mode_key}",
            style="danger",
        )

    mode_buttons = build_settings_buttons(
        settings, owner_id, mode_key, "default_set", btn_toggle
    )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:default|{owner_id}|{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_dimensions],
            [btn_document, btn_video],
            *mode_buttons,
            [btn_back],
        ]
    )


def build_sticker_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    if is_active:
        btn_toggle = InlineKeyboardButton(
            text=DISABLE,
            callback_data=f"toggle_state:sticker|{owner_id}|{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=ENABLE,
            callback_data=f"toggle_state:sticker|{owner_id}|{mode_key}",
            style="danger",
        )

    crop_ratio = settings.get("crop_ratio", "none")
    dimensions_style = "success" if crop_ratio == "none" else "primary"

    btn_dimensions = InlineKeyboardButton(
        text=STICKER_DIMENSIONS,
        callback_data=f"dimensions_menu|{owner_id}|{mode_key}",
        style=dimensions_style,
    )

    mode_buttons = build_settings_buttons(
        settings, owner_id, mode_key, "sticker_set", btn_toggle
    )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:sticker|{owner_id}|{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_dimensions],
            *mode_buttons,
            [btn_back],
        ]
    )


def build_note_markup(
    settings: dict, owner_id: int, mode_key: str, is_active: bool
) -> InlineKeyboardMarkup:
    if is_active:
        btn_toggle = InlineKeyboardButton(
            text=DISABLE,
            callback_data=f"toggle_state:note|{owner_id}|{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=ENABLE,
            callback_data=f"toggle_state:note|{owner_id}|{mode_key}",
            style="danger",
        )

    landscape_style = "primary" if settings.get("landscape") else "danger"
    portrait_style = "primary" if settings.get("portrait") else "danger"
    flip_style = "primary" if settings.get("flip_left") else "danger"
    double_rotate_style = "primary" if settings.get("double_rotate") else "danger"

    crop_align = settings.get("crop_align", "center")
    down_style = "primary" if crop_align == "bottom" else "danger"
    up_style = "primary" if crop_align == "top" else "danger"
    mute_style = "primary" if settings.get("muted") else "danger"

    btn_landscape = InlineKeyboardButton(
        text=STICKER_LANDSCAPE,
        callback_data=f"note_set:landscape|{owner_id}|{mode_key}",
        style=landscape_style,
    )
    btn_portrait = InlineKeyboardButton(
        text=STICKER_PORTRAIT,
        callback_data=f"note_set:portrait|{owner_id}|{mode_key}",
        style=portrait_style,
    )
    btn_double_rotate = InlineKeyboardButton(
        text=STICKER_DOUBLE_ROTATE,
        callback_data=f"note_set:double_rotate|{owner_id}|{mode_key}",
        style=double_rotate_style,
    )
    btn_flip = InlineKeyboardButton(
        text=STICKER_FLIP,
        callback_data=f"note_set:flip|{owner_id}|{mode_key}",
        style=flip_style,
    )
    btn_crop_down = InlineKeyboardButton(
        text=STICKER_CROP_DOWN,
        callback_data=f"note_set:crop_down|{owner_id}|{mode_key}",
        style=down_style,
    )
    btn_crop_up = InlineKeyboardButton(
        text=STICKER_CROP_UP,
        callback_data=f"note_set:crop_up|{owner_id}|{mode_key}",
        style=up_style,
    )
    btn_mute = InlineKeyboardButton(
        text=STICKER_MUTE,
        callback_data=f"note_set:mute|{owner_id}|{mode_key}",
        style=mute_style,
    )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:note|{owner_id}|{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_double_rotate],
            [btn_portrait, btn_toggle, btn_landscape],
            [btn_crop_down, btn_flip, btn_crop_up],
            [btn_mute],
            [btn_back],
        ]
    )


def build_dimensions_markup(
    settings: dict, owner_id: int, mode_key: str, prefix: str = "sticker"
) -> InlineKeyboardMarkup:
    crop_ratio = settings.get("crop_ratio", "none")

    ratio_9_16_style = "primary" if crop_ratio == "9:16" else "danger"
    ratio_16_9_style = "primary" if crop_ratio == "16:9" else "danger"

    action_name = "dim_ratio" if prefix == "sticker" else "default_dim_ratio"
    back_action = "back_to_sticker" if prefix == "sticker" else "back_to_default"

    btn_9_16 = InlineKeyboardButton(
        text=STICKER_DIM_9_16,
        callback_data=f"{action_name}:9_16|{owner_id}|{mode_key}",
        style=ratio_9_16_style,
    )
    btn_16_9 = InlineKeyboardButton(
        text=STICKER_DIM_16_9,
        callback_data=f"{action_name}:16_9|{owner_id}|{mode_key}",
        style=ratio_16_9_style,
    )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"{back_action}|{owner_id}|{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_9_16, btn_16_9],
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
        callback_data=f"setlang:en|{owner_id}|{mode_key}",
        style=eng_style,
    )
    btn_rus = InlineKeyboardButton(
        text=LANG_RUS,
        callback_data=f"setlang:ru|{owner_id}|{mode_key}",
        style=rus_style,
    )

    if lang_active:
        btn_toggle = InlineKeyboardButton(
            text=DISABLE,
            callback_data=f"toggle_state:lang|{owner_id}|{mode_key}",
            style="primary",
        )
    else:
        btn_toggle = InlineKeyboardButton(
            text=ENABLE,
            callback_data=f"toggle_state:lang|{owner_id}|{mode_key}",
            style="danger",
        )

    btn_back = InlineKeyboardButton(
        text=LANG_BACK,
        callback_data=f"back:lang|{owner_id}|{mode_key}",
        style="success",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn_toggle],
            [btn_eng, btn_rus],
            [btn_back],
        ]
    )