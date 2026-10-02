import asyncio
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import (
    ButtonStyle,
    ChatMemberStatus,
)
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    Message,
)

import CAsh
import NAMe
import Reply
import bToN
import yTFMe


BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
)

DB_PATH = os.getenv(
    "DB_PATH",
    "cache.db",
)

FFMPEG_PATH = os.getenv(
    "FFMPEG_PATH",
    ""
)

TAKEOFF_IDS = tuple(
    value.strip()
    for value in os.getenv(
        "boT_TAkeoFF",
        "",
    ).split("/")
    if value.strip()
)

DOWNLOAD_ROOT = Path("downloads")

MAX_ACTIVE_PER_SCOPE = 3
MAX_QUEUED_PER_SCOPE = 3

CALLBACK_PREFIX = "mode"

router = Router()

STATES = {}
CACHE_LOCKS = {}
ROTATION_STATES = {}


class ScopeState:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(
            MAX_ACTIVE_PER_SCOPE
        )
        self.lock = asyncio.Lock()
        self.pending = 0


def configure():
    CAsh.configure(
        sqlite3,
        DB_PATH,
    )

    NAMe.configure(
        Path,
        re,
        urlparse,
    )

    yTFMe.configure(
        Path,
        subprocess,
        FFMPEG_PATH,
    )

    bToN.configure(
        (
            ButtonStyle.DANGER,
            ButtonStyle.SUCCESS,
            ButtonStyle.PRIMARY,
        ),
        CALLBACK_PREFIX,
        Reply.MODE_VOICE,
        Reply.MODE_NORMAL,
        TAKEOFF_IDS,
    )


def settings_key(message):
    if message.chat.type == "private":
        return (
            f"user:{message.from_user.id}"
        )

    thread_id = message.message_thread_id

    if thread_id:
        return (
            f"chat:{message.chat.id}:"
            f"topic:{thread_id}"
        )

    return f"chat:{message.chat.id}"


def scope_key(message):
    if message.chat.type == "private":
        return (
            f"user:{message.from_user.id}"
        )

    thread_id = message.message_thread_id

    if thread_id:
        return (
            f"chat:{message.chat.id}:"
            f"topic:{thread_id}"
        )

    return f"chat:{message.chat.id}"


def get_state(key):
    state = STATES.get(key)

    if state is None:
        state = ScopeState()
        STATES[key] = state

    return state


async def reserve(state):
    async with state.lock:
        limit = (
            MAX_ACTIVE_PER_SCOPE
            + MAX_QUEUED_PER_SCOPE
        )

        if state.pending >= limit:
            return False

        state.pending += 1
        return True


async def release(
    key,
    state,
):
    async with state.lock:
        state.pending -= 1

        if state.pending <= 0:
            STATES.pop(
                key,
                None,
            )


async def is_authorized(message):
    if message.chat.type == "private":
        return True

    member = await message.bot.get_chat_member(
        message.chat.id,
        message.from_user.id,
    )

    return member.status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }


def settings_keyboard(mode):
    return bToN.settings_keyboard(
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        mode,
    )


def extract_urls(text):
    return re.findall(
        r"https?://[^\s<>]+",
        text or "",
    )


def cache_identity(info, url):
    extractor = (
        info.get("extractor_key")
        or info.get("extractor")
    )

    content_id = info.get("id")

    if extractor and content_id:
        return (
            f"{extractor}:{content_id}"
        )

    return (
        info.get("webpage_url")
        or info.get("original_url")
        or url
    )


def media_cache_key(
    mode,
    info,
    url,
):
    return (
        f"{mode}:"
        f"{cache_identity(info, url)}"
    )


def album_cache_key(
    mode,
    identity,
):
    return (
        f"{mode}:album:{identity}"
    )


def get_file_id(sent):
    if sent.document:
        return sent.document.file_id

    if sent.audio:
        return sent.audio.file_id

    if sent.video:
        return sent.video.file_id

    if sent.photo:
        return sent.photo[-1].file_id

    if sent.voice:
        return sent.voice.file_id

    return None


async def upload_for_cache(
    bot,
    chat_id,
    file_path,
):
    sent = await bot.send_document(
        chat_id,
        FSInputFile(file_path),
    )

    file_id = get_file_id(sent)

    try:
        await bot.delete_message(
            chat_id,
            sent.message_id,
        )
    except Exception:
        pass

    return file_id


async def prepare_item(
    mode,
    url,
    entry,
    workdir,
):
    identity = media_cache_key(
        mode,
        entry,
        url,
    )

    lock = CACHE_LOCKS.setdefault(
        identity,
        asyncio.Lock(),
    )

    async with lock:
        cached = CAsh.get_file_id(
            identity
        )

        if cached:
            return {
                "file_id": cached,
                "file_path": None,
                "cache_key": identity,
            }

        item_url = yTFMe.entry_url(
            entry
        )

        if not item_url:
            return None

        info, file_path = (
            await asyncio.to_thread(
                yTFMe.download_one,
                yt_dlp,
                item_url,
                workdir,
                mode == "voice",
            )
        )

        if mode == "voice":
            file_path = (
                await asyncio.to_thread(
                    yTFMe.prepare_voice,
                    file_path,
                )
            )

        file_path = (
            await asyncio.to_thread(
                NAMe.rename_downloaded_file,
                info,
                file_path,
            )
        )

        return {
            "file_id": None,
            "file_path": file_path,
            "cache_key": media_cache_key(
                mode,
                info,
                item_url,
            ),
        }


def cached_album_items(
    album_items,
):
    if not album_items:
        return None

    result = []

    for item in album_items:
        cache_key = item["cache_key"]

        file_id = CAsh.get_file_id(
            cache_key
        )

        if not file_id:
            return None

        result.append(
            {
                "cache_key": cache_key,
                "file_id": file_id,
            }
        )

    return result


async def prepare_collection(
    mode,
    collection,
    workdir,
):
    if not collection["is_album"]:
        entry = collection["entries"][0]
        url = yTFMe.entry_url(entry)

        if not url:
            return []

        item = await prepare_item(
            mode,
            url,
            entry,
            workdir,
        )

        return [item] if item else []

    album_key = album_cache_key(
        mode,
        collection["album_identity"],
    )

    cached = CAsh.get_album(
        album_key,
        json,
    )

    if cached:
        complete = cached_album_items(
            cached
        )

        if complete:
            return complete

    result = []

    for entry in collection["entries"]:
        url = yTFMe.entry_url(entry)

        if not url:
            continue

        item = await prepare_item(
            mode,
            url,
            entry,
            workdir,
        )

        if item:
            result.append(item)

    album_items = [
        {
            "cache_key": item["cache_key"],
        }
        for item in result
        if item["cache_key"]
    ]

    if album_items:
        CAsh.save_album(
            album_key,
            album_items,
            json,
        )

    return result


async def send_voice_item(
    message,
    item,
):
    if item["file_id"]:
        return await message.bot.send_voice(
            message.chat.id,
            item["file_id"],
            message_thread_id=(
                message.message_thread_id
            ),
            reply_to_message_id=(
                message.message_id
            ),
        )

    return await message.bot.send_voice(
        message.chat.id,
        FSInputFile(
            item["file_path"]
        ),
        message_thread_id=(
            message.message_thread_id
        ),
        reply_to_message_id=(
            message.message_id
        ),
    )


async def send_document_item(
    message,
    item,
):
    if item["file_id"]:
        return await message.bot.send_document(
            message.chat.id,
            item["file_id"],
            message_thread_id=(
                message.message_thread_id
            ),
            reply_to_message_id=(
                message.message_id
            ),
        )

    return await message.bot.send_document(
        message.chat.id,
        FSInputFile(
            item["file_path"]
        ),
        message_thread_id=(
            message.message_thread_id
        ),
        reply_to_message_id=(
            message.message_id
        ),
    )


async def send_normal_album(
    message,
    items,
):
    for start in range(
        0,
        len(items),
        8,
    ):
        chunk = items[
            start:start + 8
        ]

        if len(chunk) == 1:
            item = chunk[0]

            sent = await send_document_item(
                message,
                item,
            )

            if not item["file_id"]:
                file_id = get_file_id(
                    sent
                )

                if file_id:
                    CAsh.save_file_id(
                        item["cache_key"],
                        file_id,
                    )

            continue

        media = []

        for item in chunk:
            file_id = item["file_id"]

            if not file_id:
                file_id = (
                    await upload_for_cache(
                        message.bot,
                        message.chat.id,
                        item["file_path"],
                    )
                )

                if file_id:
                    CAsh.save_file_id(
                        item["cache_key"],
                        file_id,
                    )

            if file_id:
                media.append(
                    InputMediaDocument(
                        media=file_id
                    )
                )

        if len(media) >= 2:
            await message.bot.send_media_group(
                message.chat.id,
                media,
                message_thread_id=(
                    message.message_thread_id
                ),
            )


async def process(
    message,
    urls,
    mode,
):
    workdir = NAMe.get_download_dir(
        DOWNLOAD_ROOT,
        message.from_user.id,
    )

    try:
        if Reply.DOWNLOAD_START:
            await message.answer(
                Reply.DOWNLOAD_START
            )

        collections = []

        for url in urls:
            collection = (
                await asyncio.to_thread(
                    yTFMe.extract_entries,
                    yt_dlp,
                    url,
                )
            )

            collections.append(
                collection
            )

        if mode == "voice":
            for collection in collections:
                items = (
                    await prepare_collection(
                        mode,
                        collection,
                        workdir,
                    )
                )

                for item in items:
                    sent = (
                        await send_voice_item(
                            message,
                            item,
                        )
                    )

                    if not item["file_id"]:
                        file_id = get_file_id(
                            sent
                        )

                        if file_id:
                            CAsh.save_file_id(
                                item["cache_key"],
                                file_id,
                            )

            return

        for collection in collections:
            items = (
                await prepare_collection(
                    mode,
                    collection,
                    workdir,
                )
            )

            if items:
                await send_normal_album(
                    message,
                    items,
                )

    except Exception:
        if Reply.DOWNLOAD_FAILED:
            await message.answer(
                Reply.DOWNLOAD_FAILED
            )

    finally:
        await asyncio.to_thread(
            NAMe.cleanup,
            workdir,
        )


async def download_task(
    message,
    urls,
    mode,
    key,
    state,
):
    try:
        async with state.semaphore:
            await process(
                message,
                urls,
                mode,
            )
    finally:
        await release(
            key,
            state,
        )


def next_rotating_response(user_id):
    if not Reply.ROTATING_RESPONSES:
        return None

    index = ROTATION_STATES.get(
        user_id,
        0,
    )

    response = Reply.ROTATING_RESPONSES[
        index
    ]

    ROTATION_STATES[user_id] = (
        index + 1
    ) % len(
        Reply.ROTATING_RESPONSES
    )

    return response


async def send_rotating_response(
    message,
):
    response = next_rotating_response(
        message.from_user.id
    )

    if response is None:
        return

    if not TAKEOFF_IDS:
        await message.answer(
            response
        )
        return

    button = bToN.rotating_button(
        InlineKeyboardButton,
        Reply.BUTTON_NAMES,
    )

    if button is None:
        await message.answer(
            response
        )
        return

    await message.answer(
        response,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [button]
            ]
        ),
    )


@router.message(
    F.text == Reply.CMD_SETTINGS
)
async def settings_handler(
    message: Message,
):
    if not await is_authorized(message):
        await message.answer(
            Reply.SETTINGS_UNAUTHORIZED
        )
        return

    mode = CAsh.get_mode(
        settings_key(message)
    )

    await message.answer(
        Reply.SETTINGS_TEXT,
        reply_markup=settings_keyboard(
            mode
        ),
    )


@router.callback_query(
    F.data.startswith(
        f"{CALLBACK_PREFIX}:"
    )
)
async def mode_callback(
    callback: CallbackQuery,
):
    message = callback.message

    if not message:
        await callback.answer(
            Reply.SETTINGS_UNAUTHORIZED,
            show_alert=True,
        )
        return

    if not await is_authorized(message):
        await callback.answer(
            Reply.SETTINGS_UNAUTHORIZED,
            show_alert=True,
        )
        return

    mode = callback.data.split(
        ":",
        1,
    )[1]

    if mode not in {
        "voice",
        "normal",
    }:
        await callback.answer()
        return

    CAsh.save_mode(
        settings_key(message),
        mode,
    )

    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(
            mode
        )
    )

    await callback.answer()


@router.message(F.text)
async def text_handler(
    message: Message,
):
    text = message.text or ""
    urls = extract_urls(text)

    if urls:
        if any(
            NAMe.is_telegram_link(url)
            for url in urls
        ):
            return

        key = scope_key(message)
        state = get_state(key)

        if not await reserve(state):
            return

        mode = CAsh.get_mode(
            settings_key(message)
        )

        asyncio.create_task(
            download_task(
                message,
                urls,
                mode,
                key,
                state,
            )
        )

        return

    if message.chat.type == "private":
        await send_rotating_response(
            message
        )
        return

    if text != Reply.TRIGGER_WORD:
        return

    await send_rotating_response(
        message
    )


@router.message()
async def non_text_handler(
    message: Message,
):
    if message.chat.type != "private":
        return

    await send_rotating_response(
        message
    )


async def main():
    configure()

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set"
        )

    bot = Bot(BOT_TOKEN)
    dispatcher = Dispatcher()

    dispatcher.include_router(router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())