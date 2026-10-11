import asyncio
import shutil
import tempfile
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
    media_type: str
    identity: str = ""
    cache_key: str = ""
    file_id: str | None = None
    file_path: Path | None = None
    filename: str | None = None
    download_job: object | None = None


@dataclass
class SharedDownload:
    task: asyncio.Task
    message: Message
    references: int = 0
    cleanup_task: asyncio.Task | None = None


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
download_tasks: dict[str, SharedDownload] = {}
download_tasks_lock = asyncio.Lock()


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
    if message.from_user is None:
        return False

    user_id = message.from_user.id
    state = _get_user_queue(user_id)

    try:
        state.queue.put_nowait(
            (
                bot,
                message,
                url,
                mode,
            )
        )
    except asyncio.QueueFull:
        return False

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
    items = []
    directory_acquired = False

    try:
        if message.from_user is None:
            return

        await bToN.acquire_download_directory(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            chat_type=message.chat.type,
        )

        directory_acquired = True

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

    finally:
        try:
            await bToN._await_cleanup(
                _release_downloads(items)
            )
        finally:
            if directory_acquired:
                await bToN._await_cleanup(
                    bToN.release_download_directory(
                        user_id=message.from_user.id,
                        chat_id=message.chat.id,
                        chat_type=message.chat.type,
                    )
                )


def _media_type(mode):
    if mode == bToN.MODE_VOICE:
        return bToN.MEDIA_TYPE_VOICE

    return bToN.MEDIA_TYPE_DOCUMENT


def _build_items(entries, mode):
    items = []
    media_type = _media_type(mode)

    for entry in entries:
        url = entry_url(entry)

        if not url:
            continue

        identity = entry_identity(entry)

        items.append(
            DownloadItem(
                url=url,
                mode=mode,
                media_type=media_type,
                identity=identity,
                cache_key=bToN.cache_key(
                    mode,
                    media_type,
                    url,
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

    if not tasks:
        return

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, BaseException):
            raise result


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

    async with download_tasks_lock:
        job = download_tasks.get(
            item.cache_key
        )

        if job is None:
            directory = (
                await bToN.acquire_download_directory(
                    user_id=message.from_user.id,
                    chat_id=message.chat.id,
                    chat_type=message.chat.type,
                )
            )

            try:
                task = asyncio.create_task(
                    _download_item(
                        message,
                        item,
                        state,
                        directory,
                    )
                )
            except BaseException:
                await bToN._await_cleanup(
                    bToN.release_download_directory(
                        user_id=message.from_user.id,
                        chat_id=message.chat.id,
                        chat_type=message.chat.type,
                    )
                )
                raise

            job = SharedDownload(
                task=task,
                message=message,
            )

            download_tasks[
                item.cache_key
            ] = job

        job.references += 1
        item.download_job = job

    result = await asyncio.shield(
        job.task
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
    base_directory,
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
            temp_directory = Path(
                tempfile.mkdtemp(
                    prefix=".media-",
                    dir=base_directory,
                )
            )

            try:
                return await download_one(
                    item.url,
                    item.mode,
                    temp_directory,
                )
            except BaseException:
                await bToN._await_cleanup(
                    asyncio.to_thread(
                        shutil.rmtree,
                        temp_directory,
                        True,
                    )
                )
                raise


async def _release_downloads(items):
    cleanup_jobs = []

    async with download_tasks_lock:
        for item in items:
            job = item.download_job

            if job is None:
                continue

            item.download_job = None
            job.references -= 1

            if job.references > 0:
                continue

            if (
                download_tasks.get(
                    item.cache_key
                )
                is job
            ):
                download_tasks.pop(
                    item.cache_key,
                    None,
                )

            if job.task.done():
                cleanup_jobs.append(job)
            else:
                job.task.add_done_callback(
                    lambda _, shared_job=job:
                    _schedule_download_cleanup(
                        shared_job
                    )
                )

    for job in cleanup_jobs:
        await _wait_for_shared_cleanup(job)


def _schedule_download_cleanup(job):
    if job.cleanup_task is None:
        job.cleanup_task = asyncio.create_task(
            _cleanup_shared_download(job)
        )

    return job.cleanup_task


async def _wait_for_shared_cleanup(job):
    task = _schedule_download_cleanup(job)
    await bToN._await_cleanup(task)


async def _cleanup_shared_download(job):
    try:
        result = job.task.result()
    except BaseException:
        result = None

    try:
        if result is not None:
            await bToN._await_cleanup(
                asyncio.to_thread(
                    shutil.rmtree,
                    result.path.parent,
                    True,
                )
            )
    finally:
        message = job.message

        if message.from_user is not None:
            await bToN._await_cleanup(
                bToN.release_download_directory(
                    user_id=message.from_user.id,
                    chat_id=message.chat.id,
                    chat_type=message.chat.type,
                )
            )
