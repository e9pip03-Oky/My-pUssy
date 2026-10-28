import logging
import os
import random
import re

from aiogram import Bot, F
from aiogram.types import CallbackQuery, FSInputFile, Message

from Reply import (
    ADMIN_COMMAND,
    BOT_TRIGGER,
    BUTTON_NAMES,
    EDIT_KEYWORDS,
    LANG_MSG,
    LINK_FAIL_TEXT,
    LOADING_TEXT,
    MEDIA_DOC,
    MEDIA_VIDEO,
    MODE_DENIED,
    MODE_MSG,
    MODE_NOTE,
    MODE_VOICE,
    NO_AUDIO_MSG,
    NOTE_WAIT_MSG,
    RANDOM_REPLIES,
    WAIT_VOICE_MSG,
)
from bToN import build_lang_markup, build_mode_markup, build_specific_markup
from cAsh import (
    AdtStorage,
    ButtonCycleStorage,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    ReplyCounter,
    cleanup,
    queue,
    user_dir,
)
from ediT import handle_pending_edit, set_edit_state
from TrANs import fix_format, process_translation, make_name
from yTFMe import (
    download,
    download_merge,
    get_entries,
    to_note_trim,
    to_voice,
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
):
    async def _get_random_reply_markup(chat_id: int):
        total = len(BUTTON_NAMES)
        idx = await btn_cycle.get_index(chat_id)
        markup = build_specific_markup(idx)
        await btn_cycle.advance(chat_id, total)
        return markup

    async def _process_entry(entry: dict, message: Message, workdir: str, mode: str) -> bool:
        entry_url = entry.get("webpage_url") or entry.get("url")
        if not entry_url:
            return False

        temp_id = random.randint(100, 999)
        base = os.path.join(workdir, str(temp_id))

        if mode == "voice":
            info, in_path = await download(entry_url, base)
            out_path = os.path.join(workdir, f"{temp_id}.ogg")
            if await to_voice(in_path, out_path) and os.path.exists(out_path):
                await message.reply_voice(FSInputFile(out_path))
                return True

        elif mode == "note":
            info, in_path = await download_merge(entry_url, base)
            out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
            if await to_note_trim(in_path, out_path, "0"):
                await message.reply_video_note(FSInputFile(out_path))
                return True

        else:
            info, in_path = await download_merge(entry_url, base)
            if in_path and os.path.exists(in_path):
                ext = os.path.splitext(in_path)[1]
                doc_name = f"{make_name(info)}{ext}"
                await message.reply_document(FSInputFile(in_path, filename=doc_name))
                return True

        return False

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
                entries = await get_entries(url)

                if not entries:
                    raise RuntimeError("no results")

                sent_count = 0
                for entry in entries:
                    if await _process_entry(entry, message, workdir, mode):
                        sent_count += 1
                        cleanup(chat_id, user_id, bot.id, is_private, message.message_id)

                if sent_count > 0:
                    failed = False

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

    async def _handle_media_request(message: Message, bot: Bot, text: str) -> bool:
        media = message.reply_to_message.video or message.reply_to_message.document
        if text == MODE_NOTE and not message.reply_to_message.video:
            return False
        if text == MODE_VOICE and not media:
            return False

        is_note = text == MODE_NOTE
        media_type = MEDIA_VIDEO if message.reply_to_message.video else MEDIA_DOC
        wait_msg = await message.reply(
            NOTE_WAIT_MSG if is_note else WAIT_VOICE_MSG.format(media_type)
        )

        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_private = message.chat.type == "private"
        workdir = user_dir(chat_id, user_id, bot.id, is_private)
        temp_id = random.randint(100, 999)
        in_path = os.path.join(workdir, str(temp_id))

        try:
            tg_file = await bot.get_file(media.file_id)
            await bot.download_file(tg_file.file_path, in_path)

            if is_note:
                out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
                success = await to_note_trim(in_path, out_path, "0")
                if success:
                    await message.reply_video_note(FSInputFile(out_path))
                else:
                    await message.reply(LINK_FAIL_TEXT)
            else:
                out_path = os.path.join(workdir, f"{temp_id}.ogg")
                success = await to_voice(in_path, out_path)
                if success and os.path.exists(out_path):
                    await message.reply_voice(FSInputFile(out_path))
                else:
                    await message.reply(NO_AUDIO_MSG.format(media_type))
        except Exception as exc:
            log.warning("media failed %s: %s", message.message_id, exc)
            await message.reply(LINK_FAIL_TEXT)
        finally:
            try:
                await wait_msg.delete()
            except Exception:
                pass
            cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
        return True

    async def _handle_admin(message: Message, bot: Bot, mode_key: str) -> bool:
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_channel = message.chat.type == "channel"

        if message.chat.type != "private":
            if not await _is_admin(bot, chat_id, user_id, is_channel):
                return True

        markup = build_mode_markup(
            await modes.get(mode_key), await lang.get(mode_key), user_id, mode_key
        )
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
        return True

    async def _handle_translation(message: Message, text: str, mode_key: str) -> bool:
        if any(c.upper() in fix_format(text) for c in text) or "ss" in text.lower():
            fixed_text = fix_format(text)
            if fixed_text != text:
                await message.reply(fixed_text)
                return True
        else:
            code = await lang_code.get(mode_key)
            fixed_text = await process_translation(text, code)
            if fixed_text:
                await message.reply(fixed_text)
                return True
        return False

    async def on_message(message: Message, bot: Bot):
        if not message.text:
            return
        text = message.text.strip()
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0        thread_id = message.message_thread_id
        mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)

        if await handle_pending_edit(message, bot):
            return

        if message.reply_to_message and text in (MODE_NOTE, MODE_VOICE):
            if await _handle_media_request(message, bot, text):
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
                await _process_url(message, bot, url, current_mode)
                return

        if text == ADMIN_COMMAND:
            if await _handle_admin(message, bot, mode_key):
                return

        if await lang.get(mode_key):
            if await _handle_translation(message, text, mode_key):
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
            ("toggle:", "lang:", "setlang:", "togglelang:", "back:")
        ):
            return

        parts = data.split(":")
        action = parts[0]
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id

        if action == "toggle":
            mode_chosen = parts[1]
            owner_id, mode_key = int(parts[2]), parts[3]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            await modes.set(mode_key, mode_chosen)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_mode_markup(
                    mode_chosen, new_lang, owner_id, mode_key
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

        elif action == "togglelang":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_lang = await lang.get(mode_key)
            await lang.set(mode_key, not current_lang)
            new_lang = await lang.get(mode_key)
            current_code = await lang_code.get(mode_key)
            await callback.message.edit_reply_markup(
                reply_markup=build_lang_markup(
                    new_lang, current_code, owner_id, mode_key
                )
            )

        elif action == "back":
            owner_id, mode_key = int(parts[1]), parts[2]
            if user_id != owner_id:
                await callback.answer(MODE_DENIED, show_alert=True)
                return
            current_mode = await modes.get(mode_key)
            new_lang = await lang.get(mode_key)
            await callback.message.edit_text(
                MODE_MSG,
                reply_markup=build_mode_markup(
                    current_mode, new_lang, owner_id, mode_key
                ),
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
):
    handler, callback = make_handler(counter, modes, adt, lang, lang_code, btn_cycle)
    dispatcher.message.register(handler, F.text)
    dispatcher.callback_query.register(callback)