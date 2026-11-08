import logging

from aiogram import F
from aiogram.types import CallbackQuery

from Reply import (
    ANIMATION,
    ANIMATION_MSG,
    BUTTON_NAMES,
    DEFAULT,
    LANG_MSG,
    MODE_DENIED,
    MODE_MSG,
    NOTE,
)
from bToN import (
    build_animation_markup,
    build_default_markup,
    build_dimensions_markup,
    build_lang_markup,
    build_mode_markup,
    build_note_markup,
    build_specific_markup,
)
from cAsh_Two import (
    AdtStorage,
    AllowedStorage,
    AnimationSettings,
    ButtonCycleStorage,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    NoteSettings,
    NotifStorage,
    PendingStorage,
    ReplyCounter,
)
from perM import handle_perm_callback
from poeMs import make_service_cleaner

log = logging.getLogger("voicebot")

OWNER_ACTIONS = {
    "toggle_state",
    "back_to_animation",
    "back_to_default",
    "back",
    "toggle",
    "default_menu",
    "default_toggle",
    "animation_set",
    "note_set",
    "lang",
    "setlang",
    "animation_menu",
    "note_menu",
    "dimensions_menu",
    "dim_ratio",
    "toggle_notif",
}


async def get_random_reply_markup(
    chat_id: int, btn_cycle: ButtonCycleStorage, boot_notice: str
):
    index = await btn_cycle.get_index(chat_id)
    markup = build_specific_markup(index, boot_notice)
    await btn_cycle.advance(chat_id, len(BUTTON_NAMES))
    return markup


async def _deny(callback: CallbackQuery) -> None:
    await callback.answer(MODE_DENIED, show_alert=True)


def _parse_data(data: str) -> tuple[str, str | None, int, str]:
    head, owner_part, mode_key = data.split("|", 2)
    action, field = head.split(":", 1) if ":" in head else (head, None)
    return action, field, int(owner_part), mode_key


def make_handler(
    modes: ModeStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    animation: AnimationSettings,
    note: NoteSettings,
    default: DefaultSettings,
    notif: NotifStorage,
    allowed: AllowedStorage,
    pending: PendingStorage,
    boot_notice: str,
):
    async def on_callback(callback: CallbackQuery):
        data = callback.data
        if not data or "|" not in data:
            return
        action, field, owner_id, mode_key = _parse_data(data)
        user_id = callback.from_user.id

        if action == "perm":
            await handle_perm_callback(
                callback, field, owner_id, allowed, pending, boot_notice
            )
            return

        if callback.message.chat.type == "channel":
            try:
                member = await callback.bot.get_chat_member(
                    callback.message.chat.id, user_id
                )
                if member.status not in ("administrator", "creator"):
                    await _deny(callback)
                    return
            except Exception:
                await _deny(callback)
                return
        elif user_id != owner_id and action in OWNER_ACTIONS:
            await _deny(callback)
            return

        if action == "toggle_state":
            if field == "lang":
                await lang.set(mode_key, not await lang.get(mode_key))
                await callback.message.edit_reply_markup(
                    reply_markup=build_lang_markup(
                        await lang.get(mode_key),
                        await lang_code.get(mode_key),
                        owner_id,
                        mode_key,
                    )
                )
            elif field in {"animation", "note", "default"}:
                current_mode = await modes.get(mode_key)
                if current_mode != field:
                    await modes.set_previous(mode_key, current_mode)
                    await modes.set(mode_key, field)
                else:
                    await modes.set(mode_key, await modes.get_previous(mode_key))
                new_mode = await modes.get(mode_key)
                if field == "animation":
                    markup = build_animation_markup(
                        await animation.get(mode_key),
                        owner_id,
                        mode_key,
                        new_mode == "animation",
                    )
                elif field == "note":
                    markup = build_note_markup(
                        await note.get(mode_key),
                        owner_id,
                        mode_key,
                        new_mode == "note",
                    )
                else:
                    markup = build_default_markup(
                        await default.get(mode_key),
                        owner_id,
                        mode_key,
                        new_mode == "default",
                    )
                await callback.message.edit_reply_markup(reply_markup=markup)

        elif action == "back_to_animation":
            await modes.set_last_menu(mode_key, "animation")
            await callback.message.edit_text(
                ANIMATION_MSG.format(ANIMATION),
                reply_markup=build_animation_markup(
                    await animation.get(mode_key),
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "animation",
                ),
            )

        elif action == "back_to_default":
            await modes.set_last_menu(mode_key, "main")
            await callback.message.edit_text(
                ANIMATION_MSG.format(DEFAULT),
                reply_markup=build_default_markup(
                    await default.get(mode_key),
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "default",
                ),
            )

        elif action == "back":
            await modes.set_last_menu(mode_key, "main")
            await callback.message.edit_text(
                MODE_MSG,
                reply_markup=build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    owner_id,
                    mode_key,
                    await notif.get(mode_key),
                ),
            )

        elif action == "toggle":
            current_mode = await modes.get(mode_key)
            if current_mode == field:
                await modes.set(mode_key, await modes.get_previous(mode_key))
            else:
                await modes.set_previous(mode_key, current_mode)
                await modes.set(mode_key, field)
            await callback.message.edit_reply_markup(
                reply_markup=build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    owner_id,
                    mode_key,
                    await notif.get(mode_key),
                )
            )

        elif action == "default_menu":
            await modes.set_last_menu(mode_key, "default")
            await callback.message.edit_text(
                ANIMATION_MSG.format(DEFAULT),
                reply_markup=build_default_markup(
                    await default.get(mode_key),
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "default",
                ),
            )

        elif action == "default_toggle":
            settings = await default.get(mode_key)
            settings["send_as"] = (
                "video"
                if settings.get("send_as", "document") == "document"
                else "document"
            )
            await default.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_default_markup(
                    settings,
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "default",
                )
            )

        elif action == "animation_set":
            settings = await animation.get(mode_key)
            if field == "landscape":
                settings["landscape"] = not settings["landscape"]
                if settings["landscape"]:
                    settings["portrait"] = False
            elif field == "portrait":
                settings["portrait"] = not settings["portrait"]
                if settings["portrait"]:
                    settings["landscape"] = False
            elif field == "double_rotate":
                settings["double_rotate"] = not settings.get("double_rotate", False)
            elif field == "flip_left":
                settings["flip_left"] = not settings["flip_left"]
            await animation.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_animation_markup(
                    settings,
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "animation",
                )
            )

        elif action == "note_set":
            settings = await note.get(mode_key)
            if field == "landscape":
                settings["landscape"] = not settings["landscape"]
                if settings["landscape"]:
                    settings["portrait"] = False
            elif field == "portrait":
                settings["portrait"] = not settings["portrait"]
                if settings["portrait"]:
                    settings["landscape"] = False
            elif field == "double_rotate":
                settings["double_rotate"] = not settings.get("double_rotate", False)
            elif field == "flip_left":
                settings["flip_left"] = not settings["flip_left"]
            elif field == "crop_down":
                settings["crop_align"] = (
                    "center" if settings.get("crop_align") == "bottom" else "bottom"
                )
            elif field == "crop_up":
                settings["crop_align"] = (
                    "center" if settings.get("crop_align") == "top" else "top"
                )
            elif field == "muted":
                settings["muted"] = not settings.get("muted", False)
            await note.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_note_markup(
                    settings,
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "note",
                )
            )

        elif action == "lang":
            await modes.set_last_menu(mode_key, "lang")
            await callback.message.edit_text(
                LANG_MSG,
                reply_markup=build_lang_markup(
                    await lang.get(mode_key),
                    await lang_code.get(mode_key),
                    owner_id,
                    mode_key,
                ),
            )

        elif action == "setlang":
            await lang_code.set(mode_key, field)
            await callback.message.edit_reply_markup(
                reply_markup=build_lang_markup(
                    await lang.get(mode_key), field, owner_id, mode_key
                )
            )

        elif action == "animation_menu":
            await modes.set_last_menu(mode_key, "animation")
            await callback.message.edit_text(
                ANIMATION_MSG.format(ANIMATION),
                reply_markup=build_animation_markup(
                    await animation.get(mode_key),
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "animation",
                ),
            )

        elif action == "note_menu":
            await modes.set_last_menu(mode_key, "note")
            await callback.message.edit_text(
                ANIMATION_MSG.format(NOTE),
                reply_markup=build_note_markup(
                    await note.get(mode_key),
                    owner_id,
                    mode_key,
                    await modes.get(mode_key) == "note",
                ),
            )

        elif action == "dimensions_menu":
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(
                    await animation.get(mode_key), owner_id, mode_key
                )
            )

        elif action == "dim_ratio":
            ratio = field.replace("_", ":")
            settings = await animation.get(mode_key)
            settings["crop_ratio"] = (
                "none" if settings.get("crop_ratio", "none") == ratio else ratio
            )
            await animation.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(settings, owner_id, mode_key)
            )

        elif action == "toggle_notif":
            notif_active = await notif.get(mode_key)
            await notif.set(mode_key, not notif_active)
            new_active = await notif.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    owner_id,
                    mode_key,
                    new_active,
                )
            )

        await callback.answer()

    return on_callback


def register(
    dispatcher,
    counter: ReplyCounter,
    modes: ModeStorage,
    adt: AdtStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
    animation: AnimationSettings,
    note: NoteSettings,
    default: DefaultSettings,
    file_cache: FileIdCache,
    notif: NotifStorage,
    allowed: AllowedStorage,
    pending: PendingStorage,
    boot_notice: str,
):
    from Nookie_Two import make_message_handler

    on_message, on_channel_post = make_message_handler(
        counter,
        modes,
        adt,
        lang,
        lang_code,
        btn_cycle,
        animation,
        note,
        default,
        file_cache,
        notif,
        allowed,
        pending,
        boot_notice,
    )
    dispatcher.message.register(on_message, F.text)
    dispatcher.channel_post.register(on_channel_post, F.text)
    dispatcher.message.register(make_service_cleaner(notif))
    dispatcher.channel_post.register(make_service_cleaner(notif))
    dispatcher.callback_query.register(
        make_handler(
            modes,
            lang,
            lang_code,
            animation,
            note,
            default,
            notif,
            allowed,
            pending,
            boot_notice,
        )
    )