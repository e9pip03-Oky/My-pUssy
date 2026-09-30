import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InputMediaDocument, Message

import bToN
import yTFMe
from CAsh import Database
from NAMe import QueueManager, is_telegram_link, job_directory, make_filename, scope_key
from Reply import (
    BOT_WORD,
    DOWNLOAD_FAILED_TEXT,
    EDIT_WORD,
    MODE_TEXT,
    ROTATING_REPLIES,
    STARTUP_TEXT,
    START_DOWNLOAD_TEXT,
    UNAUTHORIZED_MODE_TEXT,
)

TOKEN = os.getenv("BOT_TOKEN")
DEVELOPER_IDS_ENV = os.getenv("boT_TAkeoFF", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
DOWNLOAD_DIRECTORY = os.getenv("DOWNLOAD_DIRECTORY", "downloads")
ALBUM_BATCH_SIZE = 8
NORMAL_MODE = "normal"
VOICE_MODE = "voice"

bot = Bot(token=TOKEN, default=DefaultBotProperties())
dp = Dispatcher()
router = Router()
database = Database(DATABASE_PATH)
queues = QueueManager()


def developer_ids():
    return [int(value) for value in DEVELOPER_IDS_ENV.split("/") if value.strip().isdigit()]


def developer_markup():
    ids = developer_ids()
    if not ids:
        return None
    indexes = database.next_developer({
        "id": len(ids),
        "name": len(bToN.DEVELOPER_NAMES),
        "style": len(bToN.DEVELOPER_STYLES),
    })
    return bToN.developer_keyboard(
        ids[indexes["id"]],
        indexes["name"],
        indexes["style"],
    )


def mode_markup(mode):
    ids = developer_ids()
    if not ids:
        return bToN.mode_keyboard(mode)
    indexes = database.next_developer({
        "id": len(ids),
        "name": len(bToN.DEVELOPER_NAMES),
        "style": len(bToN.DEVELOPER_STYLES),
    })
    return bToN.mode_keyboard(
        mode,
        ids[indexes["id"]],
        indexes["name"],
        indexes["style"],
    )


def reply_kwargs(message):
    return {
        "chat_id": message.chat.id,
        "message_thread_id": message.message_thread_id,
        "reply_parameters": {"message_id": message.message_id},
    }


async def reply_text(message, text, markup=None):
    return await bot.send_message(
        **reply_kwargs(message),
        text=text,
        reply_markup=markup if markup is not None else developer_markup(),
    )


async def authorized(message, user_id):
    if message.chat.type == "private":
        return True
    member = await bot.get_chat_member(message.chat.id, user_id)
    return member.status in {"administrator", "creator"}


async def callback_authorized(callback):
    return await authorized(callback.message, callback.from_user.id)


@router.message(CommandStart())
async def start(message: Message):
    index = database.next_reply(message.from_user.id, len(ROTATING_REPLIES))
    await reply_text(message, ROTATING_REPLIES[index])


@router.message(F.text == EDIT_WORD)
async def edit_mode(message: Message):
    if not await authorized(message, message.from_user.id):
        return
    mode = database.get_mode(scope_key(
        message.chat.type,
        message.chat.id,
        message.from_user.id,
        message.message_thread_id,
    ), NORMAL_MODE)
    await reply_text(message, MODE_TEXT, mode_markup(mode))


@router.callback_query(F.data.startswith("mode:"))
async def mode_callback(callback: CallbackQuery):
    if not await callback_authorized(callback):
        await callback.answer(UNAUTHORIZED_MODE_TEXT, show_alert=True)
        return

    requested = callback.data.split(":", 1)[1]
    if requested not in {NORMAL_MODE, VOICE_MODE}:
        await callback.answer()
        return

    message = callback.message
    scope = scope_key(
        message.chat.type,
        message.chat.id,
        callback.from_user.id,
        message.message_thread_id,
    )
    current = database.get_mode(scope, NORMAL_MODE)
    selected = requested if requested != current else (
        VOICE_MODE if current == NORMAL_MODE else NORMAL_MODE
    )
    database.set_mode(scope, selected)
    await callback.answer()
    await message.edit_reply_markup(reply_markup=mode_markup(selected))


def urls(text):
    return re.findall(r"https?://[^\s]+", text or "")


def download_request(message):
    text = (message.text or message.caption or "").strip()
    return text, urls(text)


async def send_cached_document(message, path, key, name):
    cached = database.get_file_id(NORMAL_MODE, key)
    if cached:
        try:
            return await bot.send_document(
                **reply_kwargs(message),
                document=cached
            )
        except Exception:
            pass

    sent = await bot.send_document(
        **reply_kwargs(message),
        document=FSInputFile(str(path)),
    )
    if sent.document:
        database.save_file_id(NORMAL_MODE, key, sent.document.file_id, name)
    return sent


async def send_cached_voice(message, path, key, name):
    cached = database.get_file_id(VOICE_MODE, key)
    if cached:
        try:
            return await bot.send_voice(
                **reply_kwargs(message),
                voice=cached
            )
        except Exception:
            pass

    sent = await bot.send_voice(
        **reply_kwargs(message),
        voice=FSInputFile(str(path)),
    )
    if sent.voice:
        database.save_file_id(VOICE_MODE, key, sent.voice.file_id, name)
    return sent


async def send_album(message, results):
    for start in range(0, len(results), ALBUM_BATCH_SIZE):
        batch = results[start:start + ALBUM_BATCH_SIZE]
        media = []
        uncached = []

        for path, key, name in batch:
            cached = database.get_file_id(NORMAL_MODE, key)
            if cached:
                media.append(InputMediaDocument(media=cached))
            else:
                media.append(InputMediaDocument(media=FSInputFile(str(path))))
            uncached.append((key, name, cached))

        sent = await bot.send_media_group(
            **reply_kwargs(message),
            media=media,
        )

        for item, sent_message in zip(uncached, sent):
            key, name, cached = item
            if not cached and sent_message.document:
                database.save_file_id(
                    NORMAL_MODE,
                    key,
                    sent_message.document.file_id,
                    name,
                )


async def process(message, url, mode, start_message):
    scope = scope_key(
        message.chat.type,
        message.chat.id,
        message.from_user.id,
        message.message_thread_id,
    )
    queue = await queues.acquire(scope)
    if queue is None:
        await start_message.delete()
        return

    root = Path(tempfile.mkdtemp(dir=job_directory(DOWNLOAD_DIRECTORY, scope)))

    try:
        items = await asyncio.to_thread(yTFMe.entries, yt_dlp, url)
        results = []

        for index, item in enumerate(items):
            item_url = item.get("webpage_url") or item.get("url") or url
            directory = root / str(index)
            directory.mkdir(parents=True, exist_ok=True)
            name = make_filename(item)
            key = f"{url}|{index}"

            if mode == NORMAL_MODE:
                path, info = await yTFMe.download_normal_async(
                    yt_dlp, item_url, directory, name
                )
                name = make_filename(info)
                results.append((path, key, name))
            else:
                path, info = await yTFMe.download_voice_async(
                    yt_dlp, item_url, directory, name
                )
                name = make_filename(info)
                results.append((path, key, name))

        if mode == NORMAL_MODE and len(results) > 1:
            await send_album(message, results)
        else:
            for path, key, name in results:
                if mode == NORMAL_MODE:
                    await send_cached_document(message, path, key, name)
                else:
                    await send_cached_voice(message, path, key, name)

        await start_message.delete()
    except Exception:
        logging.exception("download failed")
        try:
            await start_message.edit_text(
                DOWNLOAD_FAILED_TEXT,
                reply_markup=developer_markup(),
            )
        except Exception:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)
        await queues.release(scope, queue)


@router.message()
async def messages(message: Message):
    text, found_urls = download_request(message)

    if message.chat.type == "private":
        if not found_urls:
            index = database.next_reply(message.from_user.id, len(ROTATING_REPLIES))
            await reply_text(message, ROTATING_REPLIES[index])
            return
    elif text == BOT_WORD:
        index = database.next_reply(message.from_user.id, len(ROTATING_REPLIES))
        await reply_text(message, ROTATING_REPLIES[index])
        return
    elif not found_urls:
        return

    url = found_urls[0]
    if is_telegram_link(url):
        return

    scope = scope_key(
        message.chat.type,
        message.chat.id,
        message.from_user.id,
        message.message_thread_id,
    )
    mode = database.get_mode(scope, NORMAL_MODE)
    start_message = await reply_text(message, START_DOWNLOAD_TEXT)
    asyncio.create_task(process(message, url, mode, start_message))


async def startup():
    for developer_id in developer_ids():
        try:
            await bot.send_message(
                developer_id,
                STARTUP_TEXT,
                reply_markup=developer_markup(),
            )
        except Exception:
            logging.exception("startup message failed")


async def main():
    dp.include_router(router)
    await startup()
    try:
        await dp.start_polling(bot)
    finally:
        database.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
