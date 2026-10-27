import logging
import os
import re

import yt_dlp
from aiogram import Bot, F
from aiogram.types import CallbackQuery, FSInputFile, Message

from Reply import (
    ADMIN_COMMAND, BOT_TRIGGER, FAIL_TEXT, KEYWORD, LOADING_TEXT,
    MODE_MSG, MODE_DENIED, NO_QUERY_TEXT, RANDOM_REPLIES, WAIT_TEXT, EDIT_KEYWORDS,
    LINK_FAIL_TEXT
)
from bToN import build_mode_markup, build_buttons, build_markup, parse_ids
from cAsh import AdtStorage, LangStorage, ModeStorage, ReplyCounter, VoiceCache, cleanup, queue, user_dir
from ediT import handle_edit
from yTFMe import download, download_merge, make_name, search, to_voice

log = logging.getLogger("voicebot")
URL_RE = re.compile(r"https?://\S+")

UPPER_TARGETS = set("ATFGUJNMLБИА")
BOT_NOTICE = os.environ.get("boT_NoTice", "")

def _fix_lang_text(text: str) -> str:
    res = []
    for char in text:
        if char.upper() in UPPER_TARGETS:
            res.append(char.upper())
        elif 'a' <= char.lower() <= 'z' or 'а' <= char.lower() <= 'я':
            res.append(char.lower())
        else:
            res.append(char)
    return "".join(res)

def extract_query(text: str) -> str | None:
    text = text.strip()
    if not text.startswith(KEYWORD):
        return None
    rest = text[len(KEYWORD):]
    return rest.strip() or None if (not rest or rest[0].isspace()) else None

def is_keyword_only(text: str) -> bool:
    return text.strip().startswith(KEYWORD) and not text.strip()[len(KEYWORD):].strip()

async def _is_admin(bot: Bot, chat_id: int, user_id: int, is_channel: bool) -> bool:
    if is_channel:
        chat = await bot.get_chat(chat_id)
        return chat.type == "channel"
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def make_handler(cache: VoiceCache, counter: ReplyCounter, modes: ModeStorage, adt: AdtStorage, lang: LangStorage):
    
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
                
                if mode == "voice":
                    info, in_path = await download({"url": url}, base)
                    out_path = await to_voice(in_path, workdir, make_name(info))
                    if out_path and os.path.exists(out_path):
                        sent = await message.answer_voice(FSInputFile(out_path))
                        failed = False
                        if sent.voice and info.get("id"):
                            await cache.set(f"link_voice:{info['id']}", sent.voice.file_id)
                else:
                    info, in_path = await download_merge({"url": url}, base)
                    if in_path and os.path.exists(in_path):
                        doc_name = f"{make_name(info)}{os.path.splitext(in_path)[1]}"
                        sent = await message.answer_document(FSInputFile(in_path, filename=doc_name))
                        failed = False
                        if info.get("id"):
                            await cache.set(f"link_doc:{info['id']}", sent.document.file_id)
            except Exception as exc:
                log.warning("link failed %s: %s", message.message_id, exc)
            finally:
                try: await status.delete()
                except Exception: pass
                if failed: await message.reply(LINK_FAIL_TEXT)
        finally:
            cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
            await queue.release(chat_id)

    async def _process_search(message: Message, bot: Bot, query: str):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_private = message.chat.type == "private"
        is_channel = message.chat.type == "channel"

        accepted, event = await queue.acquire(chat_id)
        if not accepted:
            return

        try:
            wait_msg = None
            if event:
                if not is_channel:
                    wait_msg = await message.reply(WAIT_TEXT)
                await queue.wait_turn(event)
                if wait_msg:
                    try: await wait_msg.delete()
                    except Exception: pass

            status = await message.reply(LOADING_TEXT)
            failed = True
            try:
                entries = await search(query[:200])
                if not entries: raise RuntimeError("no results")

                workdir = user_dir(chat_id, user_id, bot.id, is_private)
                base_name = str(message.message_id)
                sent_count = 0

                for idx, entry in enumerate(entries):
                    url = entry.get("webpage_url") or entry.get("url")
                    if not url: continue

                    video_id = entry.get("id")
                    if not video_id:
                        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
                            entry = ydl.extract_info(url, download=False)
                        video_id = entry.get("id") or ""
                    if not video_id: continue

                    cached = await cache.get(f"youtube:{video_id}")
                    if cached:
                        try:
                            await message.answer_voice(cached)
                            sent_count += 1
                            continue
                        except Exception:
                            await cache.delete(f"youtube:{video_id}")

                    base = os.path.join(workdir, f"{base_name}_{idx}")
                    info, in_path = await download(entry, base)
                    out_path = await to_voice(in_path, workdir, make_name(info))
                    
                    if out_path and os.path.exists(out_path):
                        sent = await message.answer_voice(FSInputFile(out_path))
                        sent_count += 1
                        if sent.voice: 
                            await cache.set(f"youtube:{video_id}", sent.voice.file_id)

                if sent_count > 0: failed = False
            except Exception as exc:
                log.warning("failed %s: %s", message.message_id, exc)
            finally:
                try: await status.delete()
                except Exception: pass
                if failed: await message.reply(FAIL_TEXT)
        finally:
            cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
            await queue.release(chat_id)

    async def on_message(message: Message, bot: Bot):
        if not message.text: return
        text = message.text.strip()

        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_channel = message.chat.type == "channel"
        
        thread_id = message.message_thread_id
        mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)

        if await lang.get(mode_key):
            if any(c.upper() in UPPER_TARGETS for c in text):
                fixed_text = _fix_lang_text(text)
                if fixed_text != text:
                    await message.reply(fixed_text)
                    return

        if message.reply_to_message and message.reply_to_message.voice:
            if text.startswith(EDIT_KEYWORDS):
                await handle_edit(message, bot, cache)
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

        if url_match := URL_RE.search(text):
            url = url_match.group(0)
            if "t.me/" in url or "telegram.me/" in url:
                if not extract_query(text) and not is_keyword_only(text):
                    if message.chat.type == "private":
                        idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
                        await message.reply(RANDOM_REPLIES[idx])
                    return
            else:
                current_mode = await modes.get(mode_key)
                await _process_url(message, bot, url, current_mode)
                return

        if query := extract_query(text):
            await _process_search(message, bot, query)
            return

        if message.chat.type == "private":
            if is_keyword_only(text):
                await message.reply(NO_QUERY_TEXT)
            else:
                idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
                entries = build_buttons(parse_ids(BOT_NOTICE))
                markup = build_markup(*entries[0]) if entries else None
                await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)
        elif text == BOT_TRIGGER:
            idx = await counter.next_index(user_id, len(RANDOM_REPLIES))
            entries = build_buttons(parse_ids(BOT_NOTICE))
            markup = build_markup(*entries[0]) if entries else None
            await message.reply(RANDOM_REPLIES[idx], reply_markup=markup)

    async def on_callback(callback: CallbackQuery):
        data = callback.data
        if not data.startswith(("toggle:", "lang:")):
            return
            
        parts = data.split(":")
        action = parts[0]
        owner_id = int(parts[1])
        mode_key = parts[2]
        user_id = callback.from_user.id
        
        if user_id != owner_id:
            await callback.answer(MODE_DENIED, show_alert=True)
            return

        chat_id = callback.message.chat.id
        
        if action == "toggle":
            current_mode = await modes.get(mode_key)
            new_mode = "default" if current_mode == "voice" else "voice"
            await modes.set(mode_key, new_mode)
        elif action == "lang":
            current_lang = await lang.get(mode_key)
            await lang.set(mode_key, not current_lang)

        new_mode = await modes.get(mode_key)
        new_lang = await lang.get(mode_key)
        
        await callback.message.edit_reply_markup(reply_markup=build_mode_markup(new_mode, new_lang, owner_id, mode_key))
        await callback.answer()

    return on_message, on_callback

def register(dispatcher, cache: VoiceCache, counter: ReplyCounter, modes: ModeStorage, adt: AdtStorage, lang: LangStorage):
    handler, callback = make_handler(cache, counter, modes, adt, lang)
    dispatcher.message.register(handler, F.text)
    dispatcher.callback_query.register(callback)