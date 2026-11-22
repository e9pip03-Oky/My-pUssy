import logging
import os

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from MesSA_Two import check_is_admin, send_cached
from Reply import LINK_FAIL_TEXT, LOADING_TEXT, WAIT_TEXT
from TrANs import fix_format, has_formatting_chars, make_name, process_translation
from cAsh import (
    cleanup,
    file_locks,
    get_mode_context,
    queue,
    safe_delete,
    user_dir,
)
from cAsh_Two import (
    AdtStorage,
    AnimationSettings,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    NoteSettings,
)
from yTFMe import (
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
    entry_url: str,
    workdir: str,
    name: str,
    mode: str,
    mode_key: str,
    note: NoteSettings,
    default: DefaultSettings,
    settings: dict | None,
    cache_settings: dict | None,
    file_cache: FileIdCache | None,
) -> bool:
    base = os.path.join(workdir, name)

    if mode == "voice":
        _, in_path = await download(entry_url, base)
        out_path = os.path.join(workdir, f"{name}_voice.ogg")
        if not await to_voice(in_path, out_path) or not os.path.exists(out_path):
            return False
        sent = await message.reply_voice(
            FSInputFile(out_path, filename=f"{name}.ogg")
        )
        if file_cache:
            await file_cache.set(entry_url, mode, sent.voice.file_id, settings)
        return True

    if mode == "note":
        _, in_path = await download_merge(entry_url, base)
        out_path = os.path.join(workdir, f"{name}_note.mp4")
        note_settings = await note.get(mode_key)
        if not await to_note_trim(in_path, out_path, note_settings, "0"):
            return False
        sent = await message.reply_video_note(
            FSInputFile(out_path, filename=f"{name}.mp4")
        )
        if file_cache:
            await file_cache.set(
                entry_url, mode, sent.video_note.file_id, note_settings
            )
        return True

    if mode == "animation":
        _, in_path = await download_merge(entry_url, base)
        out_path = os.path.join(workdir, f"{name}_animation.mp4")
        if not await to_animation(in_path, out_path, settings) or not os.path.exists(
            out_path
        ):
            return False
        sent = await message.reply_animation(
            FSInputFile(out_path, filename=f"{name}.mp4")
        )
        if file_cache:
            await file_cache.set(entry_url, mode, sent.animation.file_id, settings)
        return True

    _, in_path = await download_merge(entry_url, base)
    if not in_path or not os.path.exists(in_path):
        return False

    send_as = (await default.get(mode_key)).get("send_as", "document")
    ext = os.path.splitext(in_path)[1]
    doc_name = f"{name}{ext}"

    if send_as == "video":
        sent = await message.reply_video(
            FSInputFile(in_path, filename=doc_name)
        )
        if file_cache and sent.video:
            await file_cache.set(
                entry_url, mode, sent.video.file_id, cache_settings
            )
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
    mode_key: str,
    name: str,
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
        entry_url,
        workdir,
        name,
        mode,
        mode_key,
        note,
        default,
        settings,
        cache_settings,
        file_cache,
    )


async def _try_cached_send(
    entries: list[dict],
    message: Message,
    mode: str,
    cache_settings: dict | None,
    file_cache: FileIdCache,
) -> bool:
    cached_items: list[tuple[str, str]] = []
    for entry in entries:
        entry_url = entry.get("webpage_url") or entry.get("url")
        if not entry_url:
            return False
        cached = await file_cache.get(entry_url, mode, cache_settings)
        if not cached:
            return False
        cached_items.append((entry_url, cached))

    if not cached_items:
        return False

    for entry_url, cached in cached_items:
        if not await send_cached(cached, message, mode):
            await file_cache.delete(entry_url, mode, cache_settings)
            return False
    return True


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
    ctx = get_mode_context(message)
    chat_id, user_id = ctx.chat_id, ctx.user_id
    is_private = message.chat.type == "private"

    lock = await file_locks.get(f"{user_id}:{mode}:{url}")
    async with lock:
        try:
            entries = await get_entries(url)
        except Exception as exc:
            log.warning("entries failed %s: %s", message.message_id, exc)
            await message.reply(LINK_FAIL_TEXT)
            return

        if not entries:
            await message.reply(LINK_FAIL_TEXT)
            return

        settings = await animation.get(mode_key) if mode == "animation" else None
        cache_settings = settings
        if mode == "default":
            cache_settings = await default.get(mode_key)
        elif mode == "note":
            cache_settings = await note.get(mode_key)

        if await _try_cached_send(
            entries, message, mode, cache_settings, file_cache
        ):
            return

        accepted, waited = await queue.acquire(chat_id)
        if not accepted:
            return

        wait_message: Message | None = None
        used_prefixes: list[str] = []
        try:
            if waited:
                wait_message = await message.reply(WAIT_TEXT)
            status = await message.reply(LOADING_TEXT)
            failed = True
            try:
                workdir = user_dir(chat_id, user_id, bot.id, is_private)
                sent_count = 0
                for entry in entries:
                    name = make_name(entry)
                    used_prefixes.append(name)
                    if await process_entry(
                        entry,
                        message,
                        workdir,
                        mode,
                        mode_key,
                        name,
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
            cleanup(chat_id, user_id, bot.id, is_private, *used_prefixes)
            await queue.release(chat_id)


async def handle_admin_logic(
    message: Message,
    bot: Bot,
    mode_key: str,
    adt: AdtStorage,
    new_message_id: int | None = None,
) -> bool:
    chat_id = message.chat.id
    if message.chat.type != "private":
        user_id = message.from_user.id if message.from_user else 0
        if not await check_is_admin(
            bot, chat_id, user_id, message.chat.type == "channel"
        ):
            return False
    old_messages = await adt.get_messages(mode_key)
    if len(old_messages) >= 3:
        old = old_messages.pop(0)
        try:
            await bot.delete_message(chat_id, old)
        except Exception:
            pass
    if new_message_id is not None:
        old_messages.append(new_message_id)
    await adt.save_messages(mode_key, old_messages)
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
