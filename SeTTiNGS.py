import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InputMediaDocument,
    Message,
    ReplyParameters,
)

import CAsh
import Reply
import bToN
from NAMe import (
    build_filename,
    unique_filename,
)
from yTFMe import (
    download_one,
    entry_identity,
    entry_url,
    get_entries,
)


@dataclass
class DownloadItem:
    url: str
    mode: str
    identity: str = ""
    cache_key: str = ""
    file_id: str | None = None
    file_path: Path | None = None
    filename: str | None = None


@dataclass
class UserQueue:
    queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(
            maxsize=bToN.MAX_QUEUED_DOWNLOADS
        )
    )
    semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(
            bToN.MAX_ACTIVE_DOWNLOADS
        )
    )
    workers: list[asyncio.Task] = field(
        default_factory=list
    )


user_queues: dict[int, UserQueue] = {}
cache_locks: dict[str, asyncio.Lock] = {}


def _get_cache_lock(key):
    lock = cache_locks.get(key)

    if lock is None:
        lock = asyncio.Lock()
        cache_locks[key] = lock

    return lock


def _get_user_queue(user_id):
    state = user_queues.get(user_id)

    if state is None:
        state = UserQueue()
        user_queues[user_id] = state

    if not state.workers:
        for _ in range(
            bToN.MAX_ACTIVE_DOWNLOADS
        ):
            state.workers.append(
                asyncio.create_task(
                    _worker(state)
                )
            )

    return state


async def submit(
    bot: Bot,
    message: Message,
    url,
    mode,
):
    user_id = message.from_user.id
    state = _get_user_queue(user_id)

    if state.queue.full():
        return False

    await state.queue.put(
        (bot, message, url, mode)
    )

    return True


async def _worker(state):
    while True:
        bot, message, url, mode = (
            await state.queue.get()
        )

        try:
            await _process(
                bot,
                message,
                url,
                mode,
                state,
            )
        finally:
            state.queue.task_done()


async def _process(
    bot,
    message,
    url,
    mode,
    state,
):
    try:
        entries = await get_entries(url)

        items = _build_items(
            entries,
            mode,
        )

        if not items:
            raise ValueError(
                "No downloadable items"
            )

        await _prepare_items(
            message,
            items,
            state,
        )

        if mode == bToN.MODE_VOICE:
            await _send_voices(
                bot,
                message,
                items,
            )
        else:
            await _send_documents(
                bot,
                message,
                items,
            )

    except Exception:
        await _send_failure(message)


def _build_items(entries, mode):
    items = []

    for entry in entries:
        url = entry_url(entry)

        if not url:
            continue

        identity = entry_identity(entry)

        items.append(
            DownloadItem(
                url=url,
                mode=mode,
                identity=identity,
                cache_key=bToN.cache_key(
                    mode,
                    identity,
                ),
            )
        )

    return items


async def _prepare_items(
    message,
    items,
    state,
):
    tasks = [
        asyncio.create_task(
            _prepare_item(
                message,
                item,
                state,
            )
        )
        for item in items
    ]

    await asyncio.gather(*tasks)


async def _prepare_item(
    message,
    item,
    state,
):
    cached_file_id = await CAsh.get_file_id(
        item.cache_key
    )

    if cached_file_id:
        item.file_id = cached_file_id
        return

    lock = _get_cache_lock(
        item.cache_key
    )

    async with lock:
        cached_file_id = await CAsh.get_file_id(
            item.cache_key
        )

        if cached_file_id:
            item.file_id = cached_file_id
            return

        async with state.semaphore:
            result = await download_one(
                item.url,
                item.mode,
                bToN.download_directory(
                    message.from_user.id
                ),
            )

        item.file_path = result.path

        extension = (
            "ogg"
            if item.mode == bToN.MODE_VOICE
            else result.path.suffix.lstrip(".")
        )

        filename = build_filename(
            result.info,
            extension,
        )

        item.filename = unique_filename(
            result.path.parent,
            filename,
        ).name


def _reply_parameters(message):
    return ReplyParameters(
        message_id=message.message_id,
    )


async def _send_failure(message):
    if Reply.DOWNLOAD_FAILED:
        await message.reply(
            Reply.DOWNLOAD_FAILED
        )


async def _send_documents(
    bot,
    message,
    items,
):
    for start in range(
        0,
        len(items),
        bToN.ALBUM_BATCH_SIZE,
    ):
        batch = items[
            start:start + bToN.ALBUM_BATCH_SIZE
        ]

        if len(batch) == 1:
            await _send_document(
                bot,
                message,
                batch[0],
            )
        else:
            await _send_document_album(
                bot,
                message,
                batch,
            )


async def _send_document_album(
    bot,
    message,
    items,
):
    media = []

    for item in items:
        if item.file_id:
            media.append(
                InputMediaDocument(
                    media=item.file_id,
                )
            )
        else:
            media.append(
                InputMediaDocument(
                    media=FSInputFile(
                        item.file_path,
                        filename=item.filename,
                    )
                )
            )

    result = await bot.send_media_group(
        chat_id=message.chat.id,
        media=media,
        reply_parameters=_reply_parameters(
            message
        ),
    )

    for sent, item in zip(result, items):
        if sent.document:
            item.file_id = sent.document.file_id

            await CAsh.save_file_id(
                item.cache_key,
                item.file_id,
            )


async def _send_document(
    bot,
    message,
    item,
):
    if item.file_id:
        result = await bot.send_document(
            chat_id=message.chat.id,
            document=item.file_id,
            reply_parameters=_reply_parameters(
                message
            ),
        )
    else:
        result = await bot.send_document(
            chat_id=message.chat.id,
            document=FSInputFile(
                item.file_path,
                filename=item.filename,
            ),
            reply_parameters=_reply_parameters(
                message
            ),
        )

    if result.document:
        item.file_id = result.document.file_id

        await CAsh.save_file_id(
            item.cache_key,
            item.file_id,
        )


async def _send_voices(
    bot,
    message,
    items,
):
    for item in items:
        await _send_voice(
            bot,
            message,
            item,
        )


async def _send_voice(
    bot,
    message,
    item,
):
    if item.file_id:
        result = await bot.send_voice(
            chat_id=message.chat.id,
            voice=item.file_id,
            reply_parameters=_reply_parameters(
                message
            ),
        )
    else:
        result = await bot.send_voice(
            chat_id=message.chat.id,
            voice=FSInputFile(
                item.file_path,
                filename=item.filename,
            ),
            reply_parameters=_reply_parameters(
                message
            ),
        )

    if result.voice:
        item.file_id = result.voice.file_id

        await CAsh.save_file_id(
            item.cache_key,
            item.file_id,
        )