import logging
import os
import random

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import (
    LINK_FAIL_TEXT,
    LOADING_TEXT,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_VIDEO,
    MODE_DEFAULT,
    MODE_MSG,
    MODE_NOTE,
    MODE_STICKER,
    MODE_VOICE,
    NO_AUDIO_MSG,
    NOTE_WAIT_MSG,
    STATUS_MSG,
    WAIT_VOICE_MSG,
)
from bToN import build_mode_markup
from cAsh import (
    AdtStorage,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    StickerSettings,
    cleanup,
    queue,
    user_dir,
)
from TrANs import fix_format, has_formatting_chars, make_name, process_translation
from yTFMe import (
    MAX_FILESIZE,
    download,
    download_merge,
    get_entries,
    to_note_trim,
    to_sticker,
    to_voice,
)

log = logging.getLogger("voicebot")


async def send_cached(file_id: str, message: Message, mode: str) -> bool:
    try:
        if mode == "voice":
            await message.reply_voice(file_id)
        elif mode == "note":
            await message.reply_video_note(file_id)
        elif mode == "sticker":
            await message.reply_animation(file_id)
        else:
            try:
                await message.reply_video(file_id)
            except Exception:
                await message.reply_document(file_id)
        return True
    except Exception as exc:
        log.warning("cached file_id failed: %s", exc)
        return False


async def process_entry(
    entry: dict,
    message: Message,
    workdir: str,
    mode: str,
    temp_id: int,
    settings: dict | None = None,
    file_cache: FileIdCache | None = None,
) -> bool:
    entry_url = entry.get("webpage_url") or entry.get("url")
    if not entry_url:
        return False
    if file_cache:
        cached = await file_cache.get(entry_url, mode, settings)
        if cached:
            if await send_cached(cached, message, mode):
                return True
            await file_cache.delete(entry_url, mode, settings)
    base = os.path.join(workdir, str(temp_id))
    if mode == "voice":
        info, in_path = await download(entry_url, base)
        out_path = os.path.join(workdir, f"{temp_id}.ogg")
        if await to_voice(in_path, out_path) and os.path.exists(out_path):
            sent = await message.reply_voice(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(entry_url, mode, sent.voice.file_id, settings)
            return True
        return False
    elif mode == "note":
        info, in_path = await download_merge(entry_url, base)
        out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
        if await to_note_trim(in_path, out_path, "0"):
            sent = await message.reply_video_note(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(entry_url, mode, sent.video_note.file_id, settings)
            return True
        return False
    elif mode == "sticker":
        info, in_path = await download_merge(entry_url, base)
        out_path = os.path.join(workdir, f"{temp_id}_sticker.mp4")
        if await to_sticker(in_path, out_path, settings) and os.path.exists(out_path):
            sent = await message.reply_animation(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(entry_url, mode, sent.animation.file_id, settings)
            return True
        return False
    else:
        info, in_path = await download_merge(entry_url, base)
        if in_path and os.path.exists(in_path):
            ext = os.path.splitext(in_path)[1]
            doc_name = f"{make_name(info)}{ext}"
            sent = await message.reply_document(
                FSInputFile(in_path, filename=doc_name)
            )
            if file_cache:
                if sent.video:
                    await file_cache.set(
                        entry_url, mode, sent.video.file_id, settings
                    )
                elif sent.document:
                    await file_cache.set(
                        entry_url, mode, sent.document.file_id, settings
                    )
            return True
        return False


async def process_url(
    message: Message,
    bot: Bot,
    url: str,
    mode_key: str,
    mode: str,
    sticker: StickerSettings,
    file_cache: FileIdCache,
):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    is_private = message.chat.type == "private"
    accepted, event = await queue.acquire(chat_id)
    if not accepted:
        return
    if event:
        await queue.wait_turn(event)
    settings = await sticker.get(mode_key) if mode == "sticker" else None
    used_ids: list[int] = []
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
                temp_id = random.randint(100, 999)
                used_ids.append(temp_id)
                if await process_entry(
                    entry, message, workdir, mode, temp_id, settings, file_cache
                ):
                    sent_count += 1
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
        cleanup(
            chat_id,
            user_id,
            bot.id,
            is_private,
            message.message_id,
            *used_ids,
        )
        await queue.release(chat_id)


async def handle_media_request(
    message: Message,
    bot: Bot,
    text: str,
    sticker: StickerSettings,
    file_cache: FileIdCache,
) -> bool:
    reply = message.reply_to_message
    
    is_video = bool(reply.video or (reply.document and reply.document.mime_type and "video" in reply.document.mime_type))
    
    media = reply.video or reply.document or reply.audio or reply.voice
    if text == MODE_NOTE and not is_video:
        return False
    if text == MODE_STICKER and not is_video:
        return False
    if text == MODE_VOICE and not media:
        return False
        
    is_note = text == MODE_NOTE
    is_sticker = text == MODE_STICKER
    media_file_id = media.file_id
    detail = "direct"
    
    if not is_sticker:
        cached = await file_cache.get_by_source(media_file_id, f"direct_{text}", detail)
        if cached:
            try:
                if text == MODE_VOICE:
                    await message.reply_voice(cached)
                elif text == MODE_NOTE:
                    await message.reply_video_note(cached)
                return True
            except Exception:
                await file_cache.delete_by_source(
                    media_file_id, f"direct_{text}", detail
                )
                
    if reply.video:
        media_type = MEDIA_VIDEO
    elif reply.document:
        media_type = MEDIA_DOC
    else:
        media_type = MEDIA_AUDIO
        
    wait_msg = await message.reply(
        NOTE_WAIT_MSG if (is_note or is_sticker) else WAIT_VOICE_MSG.format(media_type)
    )
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    is_private = message.chat.type == "private"
    thread_id = message.message_thread_id
    mode_key = f"{chat_id}:{thread_id}" if thread_id else str(chat_id)
    workdir = user_dir(chat_id, user_id, bot.id, is_private)
    temp_id = random.randint(100, 999)
    in_path = os.path.join(workdir, str(temp_id))
    
    try:
        tg_file = await bot.get_file(media.file_id)
        await bot.download_file(tg_file.file_path, in_path)
        if os.path.getsize(in_path) > MAX_FILESIZE:
            await message.reply(LINK_FAIL_TEXT)
            return True
            
        if is_sticker:
            out_path = os.path.join(workdir, f"{temp_id}_sticker.mp4")
            settings = await sticker.get(mode_key)
            success = await to_sticker(in_path, out_path, settings)
            if success and os.path.exists(out_path):
                await message.reply_animation(FSInputFile(out_path))
            else:
                await message.reply(LINK_FAIL_TEXT)
        elif is_note:
            out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
            success = await to_note_trim(in_path, out_path, "0")
            if success:
                sent = await message.reply_video_note(FSInputFile(out_path))
                await file_cache.set_by_source(
                    media_file_id, f"direct_{text}", detail, sent.video_note.file_id
                )
            else:
                await message.reply(LINK_FAIL_TEXT)
        else:
            out_path = os.path.join(workdir, f"{temp_id}.ogg")
            success = await to_voice(in_path, out_path)
            if success and os.path.exists(out_path):
                sent = await message.reply_voice(FSInputFile(out_path))
                await file_cache.set_by_source(
                    media_file_id, f"direct_{text}", detail, sent.voice.file_id
                )
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
        cleanup(
            chat_id,
            user_id,
            bot.id,
            is_private,
            message.message_id,
            temp_id,
        )
    return True


async def handle_admin(
    message: Message,
    bot: Bot,
    mode_key: str,
    modes: ModeStorage,
    lang: LangStorage,
    adt: AdtStorage,
    sticker: StickerSettings,
    is_admin_func,
) -> bool:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    is_channel = message.chat.type == "channel"
    if message.chat.type != "private":
        if not await is_admin_func(bot, chat_id, user_id, is_channel):
            return True
    sticker_state = await sticker.get(mode_key)
    markup = build_mode_markup(
        await modes.get(mode_key),
        await lang.get(mode_key),
        user_id,
        mode_key,
        sticker_state["enabled"],
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


async def handle_translation(
    message: Message, text: str, mode_key: str, lang_code: LangCodeStorage
) -> bool:
    if has_formatting_chars(text):
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


async def handle_status(
    message: Message, mode_key: str, modes: ModeStorage, sticker: StickerSettings
) -> bool:
    sticker_state = await sticker.get(mode_key)
    current_mode = await modes.get(mode_key)

    if sticker_state["enabled"]:
        active_mode = MODE_STICKER
    elif current_mode == "voice":
        active_mode = MODE_VOICE
    elif current_mode == "note":
        active_mode = MODE_NOTE
    else:
        active_mode = MODE_DEFAULT

    await message.reply(STATUS_MSG.format(active_mode))
    return True