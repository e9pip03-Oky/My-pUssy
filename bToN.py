STYLES = ()
SETTINGS_CALLBACK = ""
VOICE_TEXT = ""
NORMAL_TEXT = ""

ROTATING_IDS = ()
ROTATING_INDEX = 0
COLOR_INDEX = 0


def configure(
    styles,
    callback_prefix,
    voice_text,
    normal_text,
    rotating_ids,
):
    global STYLES
    global SETTINGS_CALLBACK
    global VOICE_TEXT
    global NORMAL_TEXT
    global ROTATING_IDS

    STYLES = styles
    SETTINGS_CALLBACK = callback_prefix
    VOICE_TEXT = voice_text
    NORMAL_TEXT = normal_text
    ROTATING_IDS = tuple(rotating_ids)


def settings_keyboard(
    inline_keyboard_button,
    inline_keyboard_markup,
    mode,
):
    voice_style = (
        STYLES[1]
        if mode == "voice"
        else STYLES[0]
    )

    normal_style = (
        STYLES[1]
        if mode == "normal"
        else STYLES[0]
    )

    return inline_keyboard_markup(
        inline_keyboard=[
            [
                inline_keyboard_button(
                    text=VOICE_TEXT,
                    callback_data=(
                        f"{SETTINGS_CALLBACK}:voice"
                    ),
                    style=voice_style,
                ),
                inline_keyboard_button(
                    text=NORMAL_TEXT,
                    callback_data=(
                        f"{SETTINGS_CALLBACK}:normal"
                    ),
                    style=normal_style,
                ),
            ]
        ]
    )


def rotating_button(
    inline_keyboard_button,
    names,
):
    global ROTATING_INDEX
    global COLOR_INDEX

    if not ROTATING_IDS or not names:
        return None

    user_id = ROTATING_IDS[
        ROTATING_INDEX % len(ROTATING_IDS)
    ]

    name = names[
        ROTATING_INDEX % len(names)
    ]

    style = STYLES[
        COLOR_INDEX % len(STYLES)
    ]

    ROTATING_INDEX += 1
    COLOR_INDEX += 1

    return inline_keyboard_button(
        text=name,
        url=f"tg://user?id={user_id}",
        style=style,
    )