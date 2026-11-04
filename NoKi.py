import io
import logging
import re

from aiogram import Bot, F
from aiogram.types import CallbackQuery, Message

from Reply import (
    ADMIN_COMMAND,
    BOT_TRIGGER,
    BUTTON_NAMES,
    EDIT_KEYWORDS,
    LANG_MSG,
    STICKER,
    NOTE,
    VOICE,
    DEFAULT,
    MODE_DENIED,
    MODE_MSG,
    RANDOM_REPLIES,
    STICKER_MSG,
)
from bToN import (
    build_default_markup,
    build_dimensions_markup,
    build_lang_markup,
    build_mode_markup,
    build_note_markup,
    build_specific_markup,
    build_sticker_markup,
)
from cAsh import (
    AdtStorage,
    ButtonCycleStorage,
    CookieStorage,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    NoteSettings,
    ReplyCounter,
    StickerSettings,
    get_mode_key,
)
from ediT import handle_pending_edit, set_edit_state
from MesSA import (
    handle_admin_logic,
    handle_media_request,
    handle_translation_logic,
    process_url,
)

log = logging.getLogger("voicebot")
URL_RE = re.compile(r"https?://\S+")


def make_handler(
    counter: ReplyCounter,
    modes: ModeStorage,
    adt: AdtStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
    sticker: StickerSettings,
    note: NoteSettings,
    default: DefaultSettings,
    cookies: CookieStorage,
    file_cache: FileIdCache,
):
    async def _get_random_reply_markup(chat_id: int):
        total = len(BUTTON_NAMES)
        index = await btn_cycle.get_index(chat_id)
        markup = build_specific_markup(index)
        await btn_cycle.advance(chat_id, total)
        return markup

    async def on_message(message: Message, bot: Bot):
        if message.document and message.document.file_name.startswith("cookies"):
            try:
                tg_file = await bot.get_file(message.document.file_id)
                file_content = await bot.download_file(tg_file.file_path, destination=io.BytesIO())
                await cookies.set(file_content.getvalue().decode("utf-8"))
            except Exception as e:
                log.warning("Failed to save cookies: %s", e)
            return

        if not message.text:
            return
        text = message.text.strip()
        chat_id, user_id, mode_key = get_mode_key(message)

        if await handle_pending_edit(message, bot, file_cache):
            return

        if message.reply_to_message and text in (NOTE, VOICE, STICKER):
            if await handle_media_request(message, bot, text, sticker, note, file_cache):
                return

        if message.reply_to_message and text.startswith(EDIT_KEYWORDS):
            if (
                message.reply_to_message.voice
                or message.reply_to_message.video_note
                or message.reply_to_message.video
                or message.reply_to_message.animation
            ):
                await set_edit_state(message, bot)
                return

        if url_match := URL_RE.search(text):
            url = url_match.group(0)
            if "t.me/" in url or "telegram.me/" in url:
                if message.chat.type == "private":
                    index = await counter.next_index(user_id, len(RANDOM_REPLIES))
                    markup = await _get_random_reply_markup(chat_id)
                    await message.reply(RANDOM_REPLIES[index], reply_markup=markup)
                return
            current_mode = await modes.get(mode_key)
            await process_url(
                message,
                bot,
                url,
                mode_key,
                current_mode,
                sticker,
                note,
                default,
                cookies,
                file_cache,
            )
            return

        if text == ADMIN_COMMAND:
            allowed = await handle_admin_logic(message, bot, mode_key, adt)
            if allowed:
                markup = build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    user_id,
                    mode_key,
                )
                sent_message = await message.reply(MODE_MSG, reply_markup=markup)
                if message.chat.type != "private":
                    old_messages = await adt.get_messages(mode_key)
                    old_messages.append(sent_message.message_id)
                    await adt.save_messages(mode_key, old_messages)
                return

        if await lang.get(mode_key):
            translated = await handle_translation_logic(text, mode_key, lang_code)
            if translated:
                await message.reply(translated)
                return

        if message.chat.type == "private":
            index = await counter.next_index(user_id, len(RANDOM_REPLIES))
            markup = await _get_random_reply_markup(chat_id)
            await message.reply(RANDOM_REPLIES[index], reply_markup=markup)
        elif text == BOT_TRIGGER:
            index = await counter.next_index(user_id, len(RANDOM_REPLIES))
            markup = await _get_random_reply_markup(chat_id)
            await message.reply(RANDOM_REPLIES[index], reply_markup=markup)

    async def on_callback(callback: CallbackQuery):
        data = callback.data
        if not data or "|" not in data:
            return
        head, owner_part, mode_key = data.split("|", 2)
        if ":" in head:
            action, field = head.split(":", 1)
        else:
            action, field = head, None
        user_id = callback.from_user.id
        owner_id = int(owner_part)

        if action == "toggle_state":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            if field == "lang":
                current_lang = await lang.get(mode_key)
                await lang.set(mode_key, not current_lang)
                new_lang = await lang.get(mode_key)
                current_code = await lang_code.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_lang_markup(
                        new_lang, current_code, owner_id, mode_key
                    )
                )
            elif field == "sticker":
                current_mode = await modes.get(mode_key)
                if current_mode != "sticker":
                    await modes.set_previous(mode_key, current_mode)
                    await modes.set(mode_key, "sticker")
                else:
                    previous = await modes.get_previous(mode_key)
                    await modes.set(mode_key, previous)
                new_mode = await modes.get(mode_key)
                settings = await sticker.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_sticker_markup(
                        settings, owner_id, mode_key, new_mode == "sticker"
                    )
                )
            elif field == "note":
                current_mode = await modes.get(mode_key)
                if current_mode != "note":
                    await modes.set_previous(mode_key, current_mode)
                    await modes.set(mode_key, "note")
                else:
                    previous = await modes.get_previous(mode_key)
                    await modes.set(mode_key, previous)
                new_mode = await modes.get(mode_key)
                note_settings = await note.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_note_markup(
                        note_settings, owner_id, mode_key, new_mode == "note"
                    )
                )
            elif field == "default":
                current_mode = await modes.get(mode_key)
                if current_mode != "default":
                    await modes.set_previous(mode_key, current_mode)
                    await modes.set(mode_key, "default")
                else:
                    previous = await modes.get_previous(mode_key)
                    await modes.set(mode_key, previous)
                new_mode = await modes.get(mode_key)
                default_settings = await default.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_default_markup(
                        default_settings, owner_id, mode_key, new_mode == "default"
                    )
                )

        elif action == "back_to_sticker":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG.format(STICKER),
                reply_markup=build_sticker_markup(
                    settings, owner_id, mode_key, current_mode == "sticker"
                ),
            )

        elif action == "back_to_default":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            default_settings = await default.get(mode_key)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG.format(DEFAULT),
                reply_markup=build_default_markup(
                    default_settings, owner_id, mode_key, current_mode == "default"
                ),
            )

        elif action == "back":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            await callback.message.edit_text(
                MODE_MSG,
                reply_markup=build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    owner_id,
                    mode_key,
                ),
            )

        elif action == "toggle":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_mode = await modes.get(mode_key)
            if current_mode == field:
                previous = await modes.get_previous(mode_key)
                await modes.set(mode_key, previous)
            else:
                await modes.set_previous(mode_key, current_mode)
                await modes.set(mode_key, field)
            new_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_mode_markup(
                    new_mode,
                    new_lang,
                    owner_id,
                    mode_key,
                )
            )

        elif action == "default_menu":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            default_settings = await default.get(mode_key)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG.format(DEFAULT),
                reply_markup=build_default_markup(
                    default_settings, owner_id, mode_key, current_mode == "default"
                ),
            )

        elif action == "default_toggle":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            default_settings = await default.get(mode_key)
            current_send_as = default_settings.get("send_as", "document")
            default_settings["send_as"] = (
                "video" if current_send_as == "document" else "document"
            )
            await default.set(mode_key, default_settings)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_default_markup(
                    default_settings, owner_id, mode_key, current_mode == "default"
                )
            )

        elif action in ("default_set", "note_set", "sticker_set"):
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return

            if action == "default_set":
                settings = await default.get(mode_key)
            elif action == "note_set":
                settings = await note.get(mode_key)
            else:
                settings = await sticker.get(mode_key)

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
            elif field == "flip":
                settings["flip_left"] = not settings["flip_left"]
            elif field == "crop_down":
                settings["crop_align"] = (
                    "center" if settings.get("crop_align") == "bottom" else "bottom"
                )
            elif field == "crop_up":
                settings["crop_align"] = (
                    "center" if settings.get("crop_align") == "top" else "top"
                )
            elif field == "mute":
                settings["muted"] = not settings.get("muted", False)

            if action == "default_set":
                await default.set(mode_key, settings)
                current_mode = await modes.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_default_markup(
                        settings, owner_id, mode_key, current_mode == "default"
                    )
                )
            elif action == "note_set":
                await note.set(mode_key, settings)
                current_mode = await modes.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_note_markup(
                        settings, owner_id, mode_key, current_mode == "note"
                    )
                )
            else:
                await sticker.set(mode_key, settings)
                current_mode = await modes.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_sticker_markup(
                        settings, owner_id, mode_key, current_mode == "sticker"
                    )
                )

        elif action == "lang":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            lang_active = await lang.get(mode_key)
            current_code = await lang_code.get(mode_key)
            await callback.message.edit_text(
                LANG_MSG,
                reply_markup=build_lang_markup(
                    lang_active, current_code, owner_id, mode_key
                ),
            )

        elif action == "setlang":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            await lang_code.set(mode_key, field)
            lang_active = await lang.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_lang_markup(
                    lang_active, field, owner_id, mode_key
                )
            )

        elif action == "sticker_menu":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG.format(STICKER),
                reply_markup=build_sticker_markup(
                    settings, owner_id, mode_key, current_mode == "sticker"
                ),
            )

        elif action == "note_menu":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            note_settings = await note.get(mode_key)
            current_mode = await modes.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG.format(NOTE),
                reply_markup=build_note_markup(
                    note_settings, owner_id, mode_key, current_mode == "note"
                ),
            )

        elif action == "dimensions_menu":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(
                    settings, owner_id, mode_key, "sticker"
                )
            )

        elif action == "default_dimensions_menu":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await default.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(
                    settings, owner_id, mode_key, "default"
                )
            )

        elif action == "dim_ratio":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            ratio = field.replace("_", ":")
            settings = await sticker.get(mode_key)
            current_ratio = settings.get("crop_ratio", "none")
            if current_ratio == ratio:
                settings["crop_ratio"] = "none"
            else:
                settings["crop_ratio"] = ratio
            await sticker.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(
                    settings, owner_id, mode_key, "sticker"
                )
            )

        elif action == "default_dim_ratio":
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            ratio = field.replace("_", ":")
            settings = await default.get(mode_key)
            current_ratio = settings.get("crop_ratio", "none")
            if current_ratio == ratio:
                settings["crop_ratio"] = "none"
            else:
                settings["crop_ratio"] = ratio
            await default.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(
                    settings, owner_id, mode_key, "default"
                )
            )

        await callback.answer()

    return on_message, on_callback


def register(
    dispatcher,
    counter: ReplyCounter,
    modes: ModeStorage,
    adt: AdtStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
    sticker: StickerSettings,
    note: NoteSettings,
    default: DefaultSettings,
    cookies: CookieStorage,
    file_cache: FileIdCache,
):
    handler, callback = make_handler(
        counter,
        modes,
        adt,
        lang,
        lang_code,
        btn_cycle,
        sticker,
        note,
        default,
        cookies,
        file_cache,
    )
    dispatcher.message.register(handler, F.text | F.document)
    dispatcher.callback_query.register(callback)