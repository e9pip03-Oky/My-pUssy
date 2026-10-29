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
    MODE_DENIED,
    MODE_MSG,
    MODE_NOTE,
    MODE_STICKER,
    MODE_VOICE,
    RANDOM_REPLIES,
    STICKER_MSG,
)
from bToN import (
    build_dimensions_markup,
    build_lang_markup,
    build_mode_markup,
    build_specific_markup,
    build_sticker_markup,
)
from cAsh import (
    AdtStorage,
    ButtonCycleStorage,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    ReplyCounter,
    StickerSettings,
)
from ediT import handle_pending_edit, set_edit_state
from MesSA import (
    handle_admin,
    handle_media_request,
    handle_translation,
    process_url,
)

log = logging.getLogger("voicebot")
URL_RE = re.compile(r"https?://\S+")


async def _is_admin(bot: Bot, chat_id: int, user_id: int, is_channel: bool) -> bool:
    if is_channel:
        chat = await bot.get_chat(chat_id)
        return chat.type == "channel"
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def make_handler(
    counter: ReplyCounter,
    modes: ModeStorage,
    adt: AdtStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
    sticker: StickerSettings,
    file_cache: FileIdCache,
):
    async def _get_random_reply_markup(chat_id: int):
        total = len(BUTTON_NAMES)
        idx = await btn_cycle.get_index(chat_id)
        markup = build_specific_markup(idx)
        await btn_cycle.advance(chat_id, total)
        return markup

    async def on_message(message: Message, bot: Bot):
        if not message.text:
            return
        text = message.text.strip()
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        thread_id = message.message_thread_id
        mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)

        if await handle_pending_edit(message, bot, file_cache):
            return

        if message.reply_to_message and text in (MODE_NOTE, MODE_VOICE, MODE_STICKER):
            if await handle_media_request(message, bot, text, sticker, file_cache):
                return

        if message.reply_to_message and text.startswith(EDIT_KEYWORDS):
            if (
                message.reply_to_message.voice
                or message.reply_to_message.video_note
                or message.reply_to_message.video
            ):
                await set_edit_state(message, bot)
                return

        if url_match := URL_RE.search(text):
            url = url_match.group(0)
            if "t.me/" in url or "telegram.me/" in url:
                if message.chat.type == "private":
                    idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
                    markup = await _get_random_reply_markup(chat_id)
                    await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)
                return
            else:
                current_mode = await modes.get(mode_key)
                await process_url(
                    message, bot, url, mode_key, current_mode, sticker, file_cache
                )
                return

        if text == ADMIN_COMMAND:
            if await handle_admin(
                message, bot, mode_key, modes, lang, adt, sticker, _is_admin
            ):
                return

        if await lang.get(mode_key):
            if await handle_translation(message, text, mode_key, lang_code):
                return

        if message.chat.type == "private":
            idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
            markup = await _get_random_reply_markup(chat_id)
            await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)
        elif text == BOT_TRIGGER:
            idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
            markup = await _get_random_reply_markup(chat_id)
            await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)

    async def on_callback(callback: CallbackQuery):
        data = callback.data
        if not data.startswith(
            (
                "toggle:",
                "toggle_state:",
                "lang:",
                "setlang:",
                "back:",
                "sticker_menu:",
                "sticker_set:",
                "dimensions_menu:",
                "dim_ratio:",
            )
        ):
            return
        parts = data.split(":")
        action = parts[0]
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        if action == "toggle_state":
            section = parts[1]
            owner_id, mode_key = int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            if section == "lang":
                current_lang = await lang.get(mode_key)
                await lang.set(mode_key, not current_lang)
                new_lang = await lang.get(mode_key)
                current_code = await lang_code.get(mode_key)
                await callback.message.edit_reply_markup(
                    reply_markup=build_lang_markup(
                        new_lang, current_code, owner_id, mode_key
                    )
                )
            elif section == "sticker":
                settings = await sticker.get(mode_key)
                settings["enabled"] = not settings["enabled"]
                await sticker.set(mode_key, settings)

                if settings["enabled"]:
                    current_mode = await modes.get(mode_key)
                    if current_mode != "sticker":
                        await modes.set_previous(mode_key, current_mode)
                        await modes.set(mode_key, "sticker")
                else:
                    if await modes.get(mode_key) == "sticker":
                        prev = await modes.get_previous(mode_key)
                        await modes.set(mode_key, prev)

                await callback.message.edit_reply_markup(
                    reply_markup=build_sticker_markup(settings, owner_id, mode_key)
                )

        elif action == "back":
            section = parts[1]
            owner_id, mode_key = int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            sticker_state = await sticker.get(mode_key)
            await callback.message.edit_text(
                MODE_MSG,
                reply_markup=build_mode_markup(
                    current_mode,
                    new_lang,
                    owner_id,
                    mode_key,
                    sticker_state["enabled"],
                ),
            )

        elif action == "toggle":
            mode_chosen = parts[1]
            owner_id, mode_key = int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return

            settings = await sticker.get(mode_key)
            current_mode = await modes.get(mode_key)

            if settings["enabled"]:
                settings["enabled"] = False
                await sticker.set(mode_key, settings)

            if current_mode == mode_chosen:
                prev = await modes.get_previous(mode_key)
                await modes.set(mode_key, prev)
            else:
                await modes.set_previous(mode_key, current_mode)
                await modes.set(mode_key, mode_chosen)

            new_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_mode_markup(
                    new_mode,
                    new_lang,
                    owner_id,
                    mode_key,
                    False,
                )
            )

        elif action == "lang":
            owner_id, mode_key = int(parts[1]), parts[2]
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
            code, owner_id, mode_key = parts[1], int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            await lang_code.set(mode_key, code)
            lang_active = await lang.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_lang_markup(lang_active, code, owner_id, mode_key)
            )

        elif action == "sticker_menu":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)
            await callback.message.edit_text(
                STICKER_MSG,
                reply_markup=build_sticker_markup(settings, owner_id, mode_key),
            )

        elif action == "sticker_set":
            field, owner_id, mode_key = parts[1], int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)

            if field == "landscape":
                settings["landscape"] = not settings["landscape"]
                if settings["landscape"]:
                    settings["portrait"] = False
            elif field == "portrait":
                settings["portrait"] = not settings["portrait"]
                if settings["portrait"]:
                    settings["landscape"] = False
            elif field == "flip_left":
                settings["flip_left"] = not settings["flip_left"]
                if settings["flip_left"]:
                    settings["flip_right"] = False
            elif field == "flip_right":
                settings["flip_right"] = not settings["flip_right"]
                if settings["flip_right"]:
                    settings["flip_left"] = False

            await sticker.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_sticker_markup(settings, owner_id, mode_key)
            )

        elif action == "dimensions_menu":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(settings, owner_id, mode_key)
            )

        elif action == "dim_ratio":
            ratio_part, owner_id, mode_key = parts[1], int(parts[2]), parts[3]
            ratio = ratio_part.replace("_", ":")
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            settings = await sticker.get(mode_key)

            current_ratio = settings.get("crop_ratio", "none")
            if current_ratio == ratio:
                settings["crop_ratio"] = "none"
            else:
                settings["crop_ratio"] = ratio

            await sticker.set(mode_key, settings)
            await callback.message.edit_reply_markup(
                reply_markup=build_dimensions_markup(settings, owner_id, mode_key)
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
    file_cache: FileIdCache,
):
    handler, callback = make_handler(
        counter, modes, adt, lang, lang_code, btn_cycle, sticker, file_cache
    )
    dispatcher.message.register(handler, F.text)
    dispatcher.callback_query.register(callback)