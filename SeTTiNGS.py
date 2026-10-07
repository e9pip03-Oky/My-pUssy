import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

import CAsh
import NAMe
import bToN
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
download_tasks: dict[
    str,
    asyncio.Task,
] = {}


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
        (
            bot,
            message,
            url,
            mode,
        )
    )

    return True


async def _worker(state):
    while True:
        (
            bot,
            message,
            url,
            mode,
        ) = await state.queue.get()

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
    status_message = None

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

        await _load_cached_file_ids(
            items
        )

        if not _all_cached(items):
            status_message = (
                await NAMe.send_status_message(
                    message
                )
            )

        await _prepare_items(
            message,
            items,
            state,
        )

        if mode == bToN.MODE_VOICE:
            await NAMe.send_voices(
                bot,
                message,
                items,
            )
        else:
            await NAMe.send_documents(
                bot,
                message,
                items,
            )

        await NAMe.delete_status_message(
            status_message
        )

    except Exception:
        await NAMe.show_failure(
            status_message,
            message,
        )


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


async def _load_cached_file_ids(items):
    tasks = [
        _load_cached_file_id(item)
        for item in items
    ]

    await asyncio.gather(*tasks)


async def _load_cached_file_id(item):
    item.file_id = await CAsh.get_file_id(
        item.cache_key
    )


def _all_cached(items):
    return all(
        item.file_id
        for item in items
    )


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
        if not item.file_id
    ]

    if tasks:
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

    task = download_tasks.get(
        item.cache_key
    )

    if task is None:
        task = asyncio.create_task(
            _download_item(
                message,
                item,
                state,
            )
        )

        download_tasks[item.cache_key] = task

    try:
        result = await task
    finally:
        if (
            download_tasks.get(
                item.cache_key
            )
            is task
        ):
            download_tasks.pop(
                item.cache_key,
                None,
            )

    if result is None:
        cached_file_id = (
            await CAsh.get_file_id(
                item.cache_key
            )
        )

        if cached_file_id:
            item.file_id = cached_file_id
            return

        raise RuntimeError(
            "Cached file was not found"
        )

    item.file_path = result.path

    extension = (
        "ogg"
        if item.mode == bToN.MODE_VOICE
        else result.path.suffix.lstrip(".")
    )

    item.filename = NAMe.unique_filename(
        result.path.parent,
        NAMe.build_filename(
            result.info,
            extension,
        ),
    ).name


async def _download_item(
    message,
    item,
    state,
):
    lock = _get_cache_lock(
        item.cache_key
    )

    async with lock:
        cached_file_id = (
            await CAsh.get_file_id(
                item.cache_key
            )
        )

        if cached_file_id:
            return None

        async with state.semaphore:
            return await download_one(
                item.url,
                item.mode,
                bToN.download_directory(
                    message.from_user.id
                ),
            )