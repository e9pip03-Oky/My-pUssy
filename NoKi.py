import logging
import os
import re

from aiogram import Bot, F
from aiogram.types import CallbackQuery, FSInputFile, Message
from googletrans import Translator
import yt_dlp

from Reply import (
    ADMIN_COMMAND, BOT_TRIGGER, MODE_MSG, MODE_DENIED, RANDOM_REPLIES,
    EDIT_KEYWORDS, LINK_FAIL_TEXT, BUTTON_NAMES, NO_QUERY_TEXT, LOADING_TEXT, LANG_MSG
)
from bToN import build_mode_markup, build_specific_markup, build_lang_markup
from cAsh import (
    AdtStorage, LangStorage, LangCodeStorage, ModeStorage, ReplyCounter, VoiceCache,
    ButtonCycleStorage, cleanup, queue, user_dir,
)
from ediT import set_edit_state, handle_pending_edit
from yoU import process_search, extract_query, is_keyword_only
from yTFMe import download, download_merge, make_name, to_voice

log = logging.getLogger("voicebot")
URL_RE = re.compile(r"https?://\S+")
UPPER_TARGETS = set("ATFGUJNMLБИА")

translator = Translator()


def _fix_lang_text(text: str) -> str:
    res = []
    prev_char = ""
    for char in text:
        if char == "s" and prev_char == "s":
            res.append("S")
        elif char.upper() in UPPER_TARGETS:
            res.append(char.upper())
        elif "a" <= char.lower() <= "z" or "а" <= char.lower() <= "я":
            res.append(char.lower())
        else:
            res.append(char)
        prev_char = char
    return "".join(res)


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
    cache: VoiceCache, counter: ReplyCounter, modes: ModeStorage,
    adt: AdtStorage, lang: LangStorage, lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
):
    async def _get_random_reply_markup(chat_id: int):
        total = len(BUTTON_NAMES)
        idx = await btn_cycle.get_index(chat_id)
        markup = build_specific_markup(idx)
        await btn_cycle.advance(chat_id, total)
        return markup

    async def _process_url(message: Message, bot: Bot, url: str, mode: str):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_private = message.chat.type == "private"

        accepted, event = await queue.acquire(chat_id)
        if not accepted:
            return

        try:
            status = await message.reply(LOADING_TEXT)
            failed = True
            try:
                workdir = user_dir(chat_id, user_id, bot.id, is_private)
                base = os.path.join(workdir, str(message.message_id))

                cache_key = f"link_{mode}:{url}"
                
                cached = await cache.get(cache_key)
                if cached:
                    try:
                        if mode == "voice":
                            await message.reply_voice(cached)
                        else:
                            await message.reply_document(cached)
                        failed = False
                        return
                    except Exception:
                        await cache.delete(cache_key)

                if mode == "voice":
                    info, in_path = await download(url, base)
                    out_path = await to_voice(in_path, workdir, make_name(info))
                    if out_path and os.path.exists(out_path):
                        sent = await message.reply_voice(FSInputFile(out_path))
                        failed = False
                        if sent.voice:
                            await cache.set(cache_key, sent.voice.file_id)
                else:
                    info, in_path = await download_merge(url, base)
                    if in_path and os.path.exists(in_path):
                        ext = os.path.splitext(in_path)[1]
                        doc_name = f"{make_name(info)}{ext}"
                        sent = await message.reply_document(FSInputFile(in_path, filename=doc_name))
                        failed = False
                        if sent.document:
                            await cache.set(cache_key, sent.document.file_id)
            except Exception as exc:
                log.warning("link failed %s: %s", message.message_id, exc)
            finally:
                try:
                    await status.delete()
                except Exception:
                    pass
                if failed:
                    await message.reply(LINK_FAIL_TEXT)
        finally:
            cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
            await queue.release(chat_id)

    async def on_message(message: Message, bot: Bot):
        if not message.text:
            return
        text = message.text.strip()
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_channel = message.chat.type == "channel"
        thread_id = message.message_thread_id
        mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)

        if await handle_pending_edit(message, bot, cache):
            return

        if text.startswith("يوت"):
            query = extract_query(text)
            if query and URL_RE.match(query):
                url = URL_RE.search(query).group(0)
                await _process_url(message, bot, url, "voice")
                return

        url_match = URL_RE.search(text)
        if url_match:
            url = url_match.group(0)
            if "t.me/" in url or "telegram.me/" in url:
                if not extract_query(text) and not is_keyword_only(text):
                    if message.chat.type == "private":
                        idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
                        markup = await _get_random_reply_markup(chat_id)
                        await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)
                    return
            else:
                current_mode = await modes.get(mode_key)
                await _process_url(message, bot, url, current_mode)
                return

        if text == ADMIN_COMMAND:
            if message.chat.type != "private":
                if not await _is_admin(bot, chat_id, user_id, is_channel):
                    return
            markup = build_mode_markup(await modes.get(mode_key), await lang.get(mode_key), user_id, mode_key)
            sent_msg = await message.reply(MODE_MSG, reply_markup=markup)
            if message.chat.type != "private":
                old_msgs = await adt.get_messages(mode_key)
                if len(old_msgs) >= 3:
                    old = old_msgs.pop(0)
                    try:
                        await bot.delete_message(chat_id, old)
                    except Exception:
                        pass
                old_msgs.append(sent_msg.message_id)
                await adt.save_messages(mode_key, old_msgs)
            return

        if query := extract_query(text):
            await process_search(message, bot, query, cache)
            return

        if message.reply_to_message and message.reply_to_message.voice:
            if text.startswith(EDIT_KEYWORDS):
                await set_edit_state(message, bot)
                return

        if await lang.get(mode_key):
            if any(c.upper() in UPPER_TARGETS for c in text) or "ss" in text.lower():
                fixed_text = _fix_lang_text(text)
                if fixed_text != text:
                    await message.reply(fixed_text)
                    return
            else:
                try:
                    code = await lang_code.get(mode_key)
                    res = await translator.translate(text, dest=code)
                    fixed_text = _fix_lang_text(res.text)
                    await message.reply(fixed_text)
                    return
                except Exception as exc:
                    log.warning("translation failed: %s", exc)

        if message.chat.type == "private":
            if is_keyword_only(text):
                await message.reply(NO_QUERY_TEXT)
            else:
                idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
                markup = await _get_random_reply_markup(chat_id)
                await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)
        elif text == BOT_TRIGGER:
            idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
            markup = await _get_random_reply_markup(chat_id)
            await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)

    async def on_callback(callback: CallbackQuery):
        data = callback.data
        if not data.startswith(("toggle:", "lang:", "setlang:", "togglelang:", "back:")):
            return
            
        parts = data.split(":")
        action = parts[0]
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        if action == "toggle":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_mode = await modes.get(mode_key)
            new_mode = "default" if current_mode == "voice" else "voice"
            await modes.set(mode_key, new_mode)
            new_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_reply_markup(reply_markup=build_mode_markup(new_mode, new_lang, owner_id, mode_key))

        elif action == "lang":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            lang_active = await lang.get(mode_key)
            current_code = await lang_code.get(mode_key)
            await callback.message.edit_text(LANG_MSG, reply_markup=build_lang_markup(lang_active, current_code, owner_id, mode_key))

        elif action == "setlang":
            code, owner_id, mode_key = parts[1], int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            await lang_code.set(mode_key, code)
            lang_active = await lang.get(mode_key)
            await callback.message.edit_reply_markup(reply_markup=build_lang_markup(lang_active, code, owner_id, mode_key))

        elif action == "togglelang":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_lang = await lang.get(mode_key)
            await lang.set(mode_key, not current_lang)
            new_lang = await lang.get(mode_key)
            current_code = await lang_code.get(mode_key)
            await callback.message.edit_reply_markup(reply_markup=build_lang_markup(new_lang, current_code, owner_id, mode_key))

        elif action == "back":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            new_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_text(MODE_MSG, reply_markup=build_mode_markup(new_mode, new_lang, owner_id, mode_key))

        await callback.answer()

    return on_message, on_callback


def register(
    dispatcher, cache: VoiceCache, counter: ReplyCounter, modes: ModeStorage,
    adt: AdtStorage, lang: LangStorage, lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
):
    handler, callback = make_handler(cache, counter, modes, adt, lang, lang_code, btn_cycle)
    dispatcher.message.register(handler, F.text)
    dispatcher.callback_query.register(callback)