import logging
import os
import random

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import (
    ANIMATION,
    LINK_FAIL_TEXT,
    MEDIA_ANIMATION,
    MEDIA_AUDIO,
    MEDIA_DOC,
    MEDIA_NOTE,
    MEDIA_VIDEO,
    NOTE,
    NO_AUDIO_MSG,
    NOTE_WAIT_MSG,
    VOICE,
    WAIT_VOICE_MSG,
)
from cAsh import cleanup, get_mode_key, safe_delete, user_dir
from cAsh_Two import AnimationSettings, FileIdCache, NoteSettings
from yTFMe import (
    MAX_FILESIZE,
    MAX_NOTE_FILESIZE,
    to_animation,
    to_note_trim,
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
        elif mode == "animation":
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


def _media_info(reply: Message) -> tuple[str, bool]:
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
    if reply.animation:
        return MEDIA_ANIMATION, is_video
    if reply.video:
        return MEDIA_VIDEO, is_video
    if reply.video_note:
        return MEDIA_NOTE, is_video
    if reply.document:
        return MEDIA_DOC, is_video
    return MEDIA_AUDIO, is_video


def _allowed(text: str, reply: Message, is_video: bool) -> bool:
    has_media = bool(
        reply.video
        or reply.video_note
        or reply.animation
        or reply.document
        or reply.audio
        or reply.voice
    )
    if text == NOTE and (not is_video or reply.video_note):
        return False
    if text == ANIMATION and not is_video:
        return False
    if text == VOICE and (not has_media or reply.animation):
        return False
    return True


def _wait_text(text: str, source_name: str) -> str:
    if text == NOTE:
        return NOTE_WAIT_MSG.format(source_name, NOTE)
    if text == ANIMATION:
        return NOTE_WAIT_MSG.format(source_name, ANIMATION)
    return WAIT_VOICE_MSG.format(source_name, VOICE)


async def _convert_and_send(
    message: Message,
    in_path: str,
    workdir: str,
    temp_id: int,
    text: str,
    mode_key: str,
    source_name: str,
    media_file_id: str,
    animation: AnimationSettings,
    note: NoteSettings,
    file_cache: FileIdCache,
) -> None:
    detail = "direct"
    cache_action = f"direct_{text}"

    if text == ANIMATION:
        out_path = os.path.join(workdir, f"{temp_id}_animation.mp4")
        if await to_animation(
            in_path, out_path, await animation.get(mode_key)
        ) and os.path.exists(out_path):
            await message.reply_animation(FSInputFile(out_path))
        else:
            await message.reply(LINK_FAIL_TEXT)
    elif text == NOTE:
        out_path = os.path.join(workdir, f"{temp_id}_note.mp4")
        if await to_note_trim(in_path, out_path, await note.get(mode_key), "0"):
            sent = await message.reply_video_note(FSInputFile(out_path))
            await file_cache.set_by_source(
                media_file_id, cache_action, detail, sent.video_note.file_id
            )
        else:
            await message.reply(LINK_FAIL_TEXT)
    else:
        out_path = os.path.join(workdir, f"{temp_id}_voice.ogg")
        if await to_voice(in_path, out_path) and os.path.exists(out_path):
            sent = await message.reply_voice(FSInputFile(out_path))
            await file_cache.set_by_source(
                media_file_id, cache_action, detail, sent.voice.file_id
            )
        else:
            await message.reply(NO_AUDIO_MSG.format(source_name))


async def handle_media_request(
    message: Message,
    bot: Bot,
    text: str,
    animation: AnimationSettings,
    note: NoteSettings,
    file_cache: FileIdCache,
) -> bool:
    reply = message.reply_to_message
    media = (
        reply.video
        or reply.video_note
        or reply.animation
        or reply.document
        or reply.audio
        or reply.voice
    )
    source_name, is_video = _media_info(reply)
    if not _allowed(text, reply, is_video):
        return False

    media_file_id = media.file_id
    cache_action = f"direct_{text}"

    if text != ANIMATION:
        cached = await file_cache.get_by_source(media_file_id, cache_action, "direct")
        if cached:
            try:
                if text == VOICE:
                    await message.reply_voice(cached)
                elif text == NOTE:
                    await message.reply_video_note(cached)
                return True
            except Exception:
                await file_cache.delete_by_source(
                    media_file_id, cache_action, "direct"
                )

    wait_message = await message.reply(_wait_text(text, source_name))
    chat_id, user_id, mode_key = get_mode_key(message)
    is_private = message.chat.type == "private"
    workdir = user_dir(chat_id, user_id, bot.id, is_private)
    temp_id = random.randint(100, 999)
    in_path = os.path.join(workdir, str(temp_id))

    try:
        telegram_file = await bot.get_file(media.file_id)
        await bot.download_file(telegram_file.file_path, in_path)

        size = os.path.getsize(in_path)
        if size > MAX_FILESIZE or (text == NOTE and size > MAX_NOTE_FILESIZE):
            await message.reply(LINK_FAIL_TEXT)
            return True

        await _convert_and_send(
            message,
            in_path,
            workdir,
            temp_id,
            text,
            mode_key,
            source_name,
            media_file_id,
            animation,
            note,
            file_cache,
        )
    except Exception as exc:
        log.warning("media failed %s: %s", message.message_id, exc)
        await message.reply(LINK_FAIL_TEXT)
    finally:
        await safe_delete(wait_message)
        cleanup(chat_id, user_id, bot.id, is_private, temp_id)
    return True