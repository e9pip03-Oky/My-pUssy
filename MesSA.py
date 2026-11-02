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
    MEDIA_NOTE,
    MEDIA_STICKER,
    MEDIA_VIDEO,
    MODE_DEFAULT,
    MODE_NOTE,
    MODE_STICKER,
    MODE_VOICE,
    NO_AUDIO_MSG,
    NOTE_WAIT_MSG,
    STATUS_MSG,
    TARGET_NOTE,
    TARGET_STICKER,
    TARGET_VOICE,
    WAIT_TEXT,
    WAIT_VOICE_MSG,
)
from cAsh import (
    AdtStorage,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    ModeStorage,
    NoteSettings,
    StickerSettings,
    cleanup,
    get_mode_key,
    queue,
    safe_delete,
    user_dir,
)
from TrANs import fix_format, has_formatting_chars, make_name, process_translation
from yTFMe import (
    MAX_FILESIZE,
    MAX_NOTE_FILESIZE,
    download,
    download_merge,
    get_entries,
    to_note_trim,
    to_sticker,
    to_voice,
)

log = logging.getLogger("voicebot")


async def check_is_admin(
    bot: Bot, chat_id: int, user_id: int, is_channel: bool
) -> bool:
    try:
        if is_channel:
            chat = await bot.get_chat(chat_id)
            return chat.type == "channel"
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


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
    sticker: StickerSettings,
    note: NoteSettings,
    default: DefaultSettings,
    settings: dict | None = None,
    file_cache: FileIdCache | None = None,
) -> bool:
    entry_url = entry.get("webpage_url") or entry.get("url")
    if not entry_url:
        return False

    cache_settings = settings
    if mode == "default":
        chat_id, user_id, mode_key = get_mode_key(message)
        cache_settings = await default.get(mode_key)
    elif mode == "note":
        chat_id, user_id, mode_key = get_mode_key(message)
        cache_settings = await note.get(mode_key)

    if file_cache:
        cached = await file_cache.get(entry_url, mode, cache_settings)
        if cached:
            if await send_cached(cached, message, mode):
                return True
            await file_cache.delete(entry_url, mode, cache_settings)

    base = os.path.join(workdir, str(temp_id))

    if mode == "voice":
        info, in_path = await download(entry_url, base)
        out_path = os.path.join(workdir, f"{temp_id}_voice.ogg")
        if await to_voice(in_path, out_path) and os.path.exists(out_path):
            sent = await message.reply_voice(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(entry_url, mode, sent.voice.file_id, settings)
            return True
        return False
    if mode == "note":
        info, in_path = await download_merge(entry_url, base)
        if os.path.getsize(in_path) > MAX_NOTE_FILESIZE:
            return False
        out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
        chat_id, user_id, mode_key = get_mode_key(message)
        note_settings = await note.get(mode_key)
        if await to_note_trim(in_path, out_path, note_settings, "0"):
            sent = await message.reply_video_note(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(
                    entry_url, mode, sent.video_note.file_id, note_settings
                )
            return True
        return False
    if mode == "sticker":
        info, in_path = await download_merge(entry_url, base)
        out_path = os.path.join(workdir, f"{temp_id}_sticker.mp4")
        if await to_sticker(in_path, out_path, settings) and os.path.exists(out_path):
            sent = await message.reply_animation(FSInputFile(out_path))
            if file_cache:
                await file_cache.set(entry_url, mode, sent.animation.file_id, settings)
            return True
        return False

    info, in_path = await download_merge(entry_url, base)
    if in_path and os.path.exists(in_path):
        chat_id, user_id, mode_key = get_mode_key(message)
        default_state = await default.get(mode_key)
        send_as = default_state.get("send_as", "document")

        if send_as == "video":
            out_path = os.path.join(workdir, f"{temp_id}_def.mp4")
            success = await to_sticker(in_path, out_path, default_state)
            if not success or not os.path.exists(out_path):
                out_path = in_path

            sent = await message.reply_video(FSInputFile(out_path))
            if file_cache and sent.video:
                await file_cache.set(
                    entry_url, mode, sent.video.file_id, cache_settings
                )
        else:
            ext = os.path.splitext(in_path)[1]
            doc_name = f"{make_name(info)}{ext}"
            sent = await message.reply_document(
                FSInputFile(in_path, filename=doc_name),
                disable_content_type_detection=True,
            )
            if file_cache and sent.document:
                await file_cache.set(
                    entry_url, mode, sent.document.file_id, cache_settings
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
        settings = await sticker.get(mode_key) if mode == "sticker" else None
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
                    entry,
                    message,
                    workdir,
                    mode,
                    temp_id,
                    sticker,
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
        cleanup(
            chat_id,
            user_id,
            bot.id,
            is_private,
            *used_ids,
        )
        await queue.release(chat_id)


async def handle_media_request(
    message: Message,
    bot: Bot,
    text: str,
    sticker: StickerSettings,
    note: NoteSettings,
    file_cache: FileIdCache,
) -> bool:
    reply = message.reply_to_message
    is_video = bool(
        reply.video
        or reply.video_note
        or reply.animation
        or (
            reply.document
            and reply.document.mime_type
            and "video" in reply.document.mime_type
        )
    )
    media = (
        reply.video
        or reply.video_note
        or reply.animation
        or reply.document
        or reply.audio
        or reply.voice
    )
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
        cached = await file_cache.get_by_source(
            media_file_id, f"direct_{text}", detail
        )
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
    elif reply.video_note:
        media_type = MEDIA_VIDEO
    elif reply.animation:
        media_type = MEDIA_VIDEO
    elif reply.document:
        media_type = MEDIA_DOC
    else:
        media_type = MEDIA_AUDIO

    if reply.animation:
        source_name = MEDIA_STICKER
    elif reply.video:
        source_name = MEDIA_VIDEO
    elif reply.video_note:
        source_name = MEDIA_NOTE
    elif reply.document:
        source_name = MEDIA_DOC
    else:
        source_name = MEDIA_AUDIO

    if is_note:
        target_name = TARGET_NOTE
        wait_text = NOTE_WAIT_MSG.format(source_name, target_name)
    elif is_sticker:
        target_name = TARGET_STICKER
        wait_text = NOTE_WAIT_MSG.format(source_name, target_name)
    else:
        target_name = TARGET_VOICE
        wait_text = WAIT_VOICE_MSG.format(source_name, target_name)

    wait_message = await message.reply(wait_text)

    chat_id, user_id, mode_key = get_mode_key(message)
    is_private = message.chat.type == "private"
    workdir = user_dir(chat_id, user_id, bot.id, is_private)
    temp_id = random.randint(100, 999)
    in_path = os.path.join(workdir, str(temp_id))

    try:
        telegram_file = await bot.get_file(media.file_id)
        await bot.download_file(telegram_file.file_path, in_path)

        size = os.path.getsize(in_path)
        if size > MAX_FILESIZE:
            await message.reply(LINK_FAIL_TEXT)
            return True
        if is_note and size > MAX_NOTE_FILESIZE:
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
            note_settings = await note.get(mode_key)
            success = await to_note_trim(in_path, out_path, note_settings, "0")
            if success:
                sent = await message.reply_video_note(FSInputFile(out_path))
                await file_cache.set_by_source(
                    media_file_id, f"direct_{text}", detail, sent.video_note.file_id
                )
            else:
                await message.reply(LINK_FAIL_TEXT)
        else:
            out_path = os.path.join(workdir, f"{temp_id}_voice.ogg")
            success = await to_voice(in_path, out_path)
            if success and os.path.exists(out_path):
                sent = await message.reply_voice(FSInputFile(out_path))
                await file_cache.set_by_source(
                    media_file_id, f"direct_{text}", detail, sent.voice.file_id
                )
            else:
                await message.reply(NO_AUDIO_MSG.format(source_name))
    except Exception as exc:
        log.warning("media failed %s: %s", message.message_id, exc)
        await message.reply(LINK_FAIL_TEXT)
    finally:
        await safe_delete(wait_message)
        cleanup(
            chat_id,
            user_id,
            bot.id,
            is_private,
            temp_id,
        )
    return True


async def handle_admin_logic(
    message: Message,
    bot: Bot,
    mode_key: str,
    adt: AdtStorage,
) -> bool:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    is_channel = message.chat.type == "channel"
    if message.chat.type != "private":
        if not await check_is_admin(bot, chat_id, user_id, is_channel):
            return False
        old_messages = await adt.get_messages(mode_key)
        if len(old_messages) >= 3:
            old = old_messages.pop(0)
            try:
                await bot.delete_message(chat_id, old)
            except Exception:
                pass
        await adt.save_messages(mode_key, old_messages)
    return True


async def handle_translation_logic(
    text: str, mode_key: str, lang_code: LangCodeStorage
) -> str | None:
    if has_formatting_chars(text):
        fixed_text = fix_format(text)
        if fixed_text != text:
            return fixed_text
    elif any(char.isalpha() for char in text):
        code = await lang_code.get(mode_key)
        fixed_text = await process_translation(text, code)
        if fixed_text:
            return fixed_text
    return None


async def get_status_mode(
    mode_key: str, modes: ModeStorage, sticker: StickerSettings
) -> str:
    sticker_state = await sticker.get(mode_key)
    current_mode = await modes.get(mode_key)

    if sticker_state["enabled"]:
        return MODE_STICKER
    if current_mode == "voice":
        return MODE_VOICE
    if current_mode == "note":
        return MODE_NOTE
    return MODE_DEFAULT