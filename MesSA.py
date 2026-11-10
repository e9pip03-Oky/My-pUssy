import logging  
import os  
import random  
  
from aiogram import Bot  
from aiogram.types import FSInputFile, Message  
  
from MesSA_Two import check_is_admin, send_cached  
from Reply import LINK_FAIL_TEXT, LOADING_TEXT, WAIT_TEXT  
from TrANs import fix_format, has_formatting_chars, make_name, process_translation  
from cAsh import cleanup, get_mode_key, queue, safe_delete, user_dir  
from cAsh_Two import (  
    AnimationSettings,  
    DefaultSettings,  
    FileIdCache,  
    LangCodeStorage,  
    NoteSettings,  
)  
from yTFMe import (  
    MAX_NOTE_FILESIZE,  
    download,  
    download_merge,  
    get_entries,  
    to_animation,  
    to_note_trim,  
    to_voice,  
)  
  
log = logging.getLogger("voicebot")  
  
  
async def _send_by_mode(  
    message: Message,  
    entry: dict,  
    entry_url: str,  
    base: str,  
    temp_id: int,  
    mode: str,  
    workdir: str,  
    animation: AnimationSettings,  
    note: NoteSettings,  
    default: DefaultSettings,  
    settings: dict | None,  
    cache_settings: dict | None,  
    file_cache: FileIdCache | None,  
) -> bool:  
    if mode == "voice":  
        _, in_path = await download(entry_url, base)  
        out_path = os.path.join(workdir, f"{temp_id}_voice.ogg")  
        if not await to_voice(in_path, out_path) or not os.path.exists(out_path):  
            return False  
        sent = await message.reply_voice(FSInputFile(out_path))  
        if file_cache:  
            await file_cache.set(entry_url, mode, sent.voice.file_id, settings)  
        return True  
  
    if mode == "note":  
        _, in_path = await download_merge(entry_url, base)  
        if os.path.getsize(in_path) > MAX_NOTE_FILESIZE:  
            return False  
        out_path = os.path.join(workdir, f"{temp_id}_note.mp4")  
        note_settings = await note.get(get_mode_key(message)[2])  
        if not await to_note_trim(in_path, out_path, note_settings, "0"):  
            return False  
        sent = await message.reply_video_note(FSInputFile(out_path))  
        if file_cache:  
            await file_cache.set(  
                entry_url, mode, sent.video_note.file_id, note_settings  
            )  
        return True  
  
    if mode == "animation":  
        _, in_path = await download_merge(entry_url, base)  
        out_path = os.path.join(workdir, f"{temp_id}_animation.mp4")  
        if not await to_animation(in_path, out_path, settings) or not os.path.exists(  
            out_path  
        ):  
            return False  
        sent = await message.reply_animation(FSInputFile(out_path))  
        if file_cache:  
            await file_cache.set(entry_url, mode, sent.animation.file_id, settings)  
        return True  
  
    _, in_path = await download_merge(entry_url, base)  
    if not in_path or not os.path.exists(in_path):  
        return False  
  
    send_as = (await default.get(get_mode_key(message)[2])).get(  
        "send_as", "document"  
    )  
    ext = os.path.splitext(in_path)[1]  
    doc_name = f"{make_name(entry)}{ext}"  
  
    if send_as == "video":  
        video_path = os.path.join(workdir, doc_name)  
        os.rename(in_path, video_path)  
        try:  
            sent = await message.reply_video(FSInputFile(video_path))  
            if file_cache and sent.video:  
                await file_cache.set(  
                    entry_url, mode, sent.video.file_id, cache_settings  
                )  
        finally:  
            try:  
                os.remove(video_path)  
            except OSError:  
                pass  
    else:  
        sent = await message.reply_document(  
            FSInputFile(in_path, filename=doc_name),  
            disable_content_type_detection=True,  
        )  
        if file_cache and sent.document:  
            await file_cache.set(  
                entry_url, mode, sent.document.file_id, cache_settings  
            )  
    return True  
  
  
async def process_entry(  
    entry: dict,  
    message: Message,  
    workdir: str,  
    mode: str,  
    temp_id: int,  
    animation: AnimationSettings,  
    note: NoteSettings,  
    default: DefaultSettings,  
    settings: dict | None = None,  
    file_cache: FileIdCache | None = None,  
) -> bool:  
    entry_url = entry.get("webpage_url") or entry.get("url")  
    if not entry_url:  
        return False  
  
    mode_key = get_mode_key(message)[2]  
    cache_settings = settings  
    if mode == "default":  
        cache_settings = await default.get(mode_key)  
    elif mode == "note":  
        cache_settings = await note.get(mode_key)  
  
    if file_cache:  
        cached = await file_cache.get(entry_url, mode, cache_settings)  
        if cached:  
            if await send_cached(cached, message, mode):  
                return True  
            await file_cache.delete(entry_url, mode, cache_settings)  
  
    return await _send_by_mode(  
        message,  
        entry,  
        entry_url,  
        os.path.join(workdir, str(temp_id)),  
        temp_id,  
        mode,  
        workdir,  
        animation,  
        note,  
        default,  
        settings,  
        cache_settings,  
        file_cache,  
    )  
  
  
async def process_url(  
    message: Message,  
    bot: Bot,  
    url: str,  
    mode_key: str,  
    mode: str,  
    animation: AnimationSettings,  
    note: NoteSettings,  
    default: DefaultSettings,  
    file_cache: FileIdCache,  
) -> None:  
    chat_id, user_id, _ = get_mode_key(message)  
    is_private = message.chat.type == "private"  
    accepted, waited = await queue.acquire(chat_id)  
    if not accepted:  
        return  
    wait_message: Message | None = None  
    used_ids: list[int] = []  
    try:  
        if waited:  
            wait_message = await message.reply(WAIT_TEXT)  
        settings = await animation.get(mode_key) if mode == "animation" else None  
        status = await message.reply(LOADING_TEXT)  
        failed = True  
        try:  
            workdir = user_dir(chat_id, user_id, bot.id, is_private)  
            entries = await get_entries(url)  
            if not entries:  
                raise RuntimeError("no results")  
            sent_count = 0  
            for entry in entries:  
                temp_id = random.randint(100000, 999999)  
                used_ids.append(temp_id)  
                if await process_entry(  
                    entry,  
                    message,  
                    workdir,  
                    mode,  
                    temp_id,  
                    animation,  
                    note,  
                    default,  
                    settings,  
                    file_cache,  
                ):  
                    sent_count += 1  
            if sent_count > 0:  
                failed = False  
        except Exception as exc:  
            log.warning("link failed %s: %s", message.message_id, exc)  
        finally:  
            await safe_delete(status)  
            if failed:  
                await message.reply(LINK_FAIL_TEXT)  
    finally:  
        if wait_message:  
            await safe_delete(wait_message)  
        cleanup(chat_id, user_id, bot.id, is_private, *used_ids)  
        await queue.release(chat_id)  
  
  
async def handle_admin_logic(  
    message: Message, bot: Bot, mode_key: str, adt  
) -> bool:  
    if message.chat.type != "private":  
        chat_id = message.chat.id  
        user_id = message.from_user.id if message.from_user else 0  
        if not await check_is_admin(  
            bot, chat_id, user_id, message.chat.type == "channel"  
        ):  
            return False  
    return True  
  
  
async def handle_translation_logic(  
    text: str, mode_key: str, lang_code: LangCodeStorage  
) -> str | None:  
    if has_formatting_chars(text):  
        fixed = fix_format(text)  
        return fixed if fixed != text else None  
    if not any(char.isalpha() for char in text):  
        return None  
    translated = await process_translation(text, await lang_code.get(mode_key))  
    return translated or None
