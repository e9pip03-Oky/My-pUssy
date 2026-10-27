import asyncio
import logging
import os
import re

import yt_dlp
from aiogram import Bot
from aiogram.types import FSInputFile, Message

from Reply import (
    FAIL_TEXT, KEYWORD, LOADING_TEXT, NO_QUERY_TEXT, WAIT_TEXT,
)
from cAsh import VoiceCache, cleanup, queue, user_dir
from yTFMe import download_yt, make_name, to_voice

log = logging.getLogger("voicebot")
MAX_FILESIZE = 48 * 1024 * 1024


def extract_query(text: str) -> str | None:
    text = text.strip()
    if not text.startswith(KEYWORD):
        return None
    rest = text[len(KEYWORD) :]
    return rest.strip() or None if (not rest or rest[0].isspace()) else None


def is_keyword_only(text: str) -> bool:
    return text.strip().startswith(KEYWORD) and not text.strip()[len(KEYWORD) :].strip()


def _get_playlist_entries(target: str) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch3",
        "extract_flat": True,
        "max_filesize": MAX_FILESIZE,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)

    entries = [e for e in info.get("entries") or [] if e]
    if not entries:
        return [info] if info.get("url") else []
    return sorted(entries, key=lambda e: e.get("view_count") or 0, reverse=True)[:3]


async def search(target: str) -> list[dict]:
    return await asyncio.to_thread(_get_playlist_entries, target)


async def process_search(message: Message, bot: Bot, query: str, cache: VoiceCache):
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
                try:
                    await wait_msg.delete()
                except Exception:
                    pass

        status = await message.reply(LOADING_TEXT)
        failed = True
        try:
            entries = await search(query[:200])
            if not entries:
                raise RuntimeError("no results")

            workdir = user_dir(chat_id, user_id, bot.id, is_private)
            base_name = str(message.message_id)
            sent_count = 0

            for idx, entry in enumerate(entries):
                url = entry.get("webpage_url") or entry.get("url")
                if not url:
                    continue

                video_id = entry.get("id")
                if not video_id:
                    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
                        entry = ydl.extract_info(url, download=False)
                    video_id = entry.get("id") or ""
                if not video_id:
                    continue

                cache_key = f"voice_yt:{video_id}"
                cached = await cache.get(cache_key)
                if cached:
                    try:
                        await message.reply_voice(cached)
                        sent_count += 1
                        continue
                    except Exception:
                        await cache.delete(cache_key)

                base = os.path.join(workdir, f"{base_name}_{idx}")
                info, in_path = await download_yt(url, base)
                out_path = await to_voice(in_path, workdir, make_name(info))

                if out_path and os.path.exists(out_path):
                    sent = await message.reply_voice(FSInputFile(out_path))
                    sent_count += 1
                    if sent.voice:
                        await cache.set(cache_key, sent.voice.file_id)

            if sent_count > 0:
                failed = False
        except Exception as exc:
            log.warning("failed %s: %s", message.message_id, exc)
        finally:
            try:
                await status.delete()
            except Exception:
                pass
            if failed:
                await message.reply(FAIL_TEXT)
    finally:
        cleanup(chat_id, user_id, bot.id, is_private, message.message_id)
        await queue.release(chat_id)