import asyncio
import shutil
import tempfile
from pathlib import Path

import aiosqlite
from aiogram.types import FSInputFile

import Reply
import bToN

DB_PATH = None


def _ffmpeg_path():
    return bToN.get_ffmpeg_path() or "ffmpeg"


def _ffprobe_path():
    configured_path = bToN.get_ffmpeg_path()

    if configured_path:
        path = Path(configured_path)

        if path.is_dir():
            sibling = path / "ffprobe"
        else:
            sibling = path.with_name("ffprobe")

        if sibling.is_file():
            return str(sibling)

    return shutil.which("ffprobe") or "ffprobe"


async def configure(db_path):
    global DB_PATH

    DB_PATH = str(db_path)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS audio_sources (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )
        await db.commit()


def _get_media(message):
    for attribute in ("video", "audio", "voice", "document"):
        media = getattr(message, attribute, None)

        if media is not None:
            return media, attribute

    return None, None


async def _can_inspect(message, bot):
    if message.chat.type == "private":
        return True

    if message.chat.type not in {"group", "supergroup"}:
        return False

    try:
        member = await bot.get_chat_member(
            chat_id=message.chat.id,
            user_id=bot.id,
        )
    except Exception:
        return False

    return member.status.value in bToN.ADMIN_STATUSES


async def _run_process(*args):
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    stdout, _ = await process.communicate()
    return process.returncode, stdout


async def _has_audio_stream(path):
    try:
        return_code, output = await _run_process(
            _ffprobe_path(),
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        )
    except (OSError, ValueError):
        return False

    return return_code == 0 and bool(output.strip())


async def _download_message_media(message, bot, destination):
    media, _ = _get_media(message)

    if media is None:
        return False

    try:
        telegram_file = await bot.get_file(media.file_id)

        if not telegram_file.file_path:
            return False

        await bot.download_file(
            telegram_file.file_path,
            destination=destination,
        )
    except Exception:
        return False

    try:
        path = Path(destination)
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


async def _save_source(message):
    if DB_PATH is None:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO audio_sources (
                chat_id,
                message_id
            )
            VALUES (?, ?)
            """,
            (message.chat.id, message.message_id),
        )
        await db.commit()


async def inspect_message(message, bot):
    if not await _can_inspect(message, bot):
        return

    media, media_type = _get_media(message)

    if media is None:
        return

    if media_type in {"audio", "voice"}:
        await _save_source(message)
        return

    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "source.media"

        downloaded = await _download_message_media(
            message,
            bot,
            source_path,
        )

        if not downloaded:
            return

        if await _has_audio_stream(source_path):
            await _save_source(message)


async def _is_registered(message):
    if DB_PATH is None:
        return False

    source = message.reply_to_message

    if source is None:
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT 1
            FROM audio_sources
            WHERE chat_id = ? AND message_id = ?
            """,
            (source.chat.id, source.message_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def _extract_audio(input_path, output_path):
    return_code, _ = await _run_process(
        _ffmpeg_path(),
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(output_path),
    )

    return (
        return_code == 0
        and output_path.is_file()
        and output_path.stat().st_size > 0
    )


async def _show_failure(status_message):
    try:
        await status_message.edit_text(Reply.AUDIO_START_FAILED)
    except Exception:
        pass


async def handle_start(message, bot):
    source = message.reply_to_message

    if source is None:
        return False

    if not await _is_registered(message):
        return False

    media, _ = _get_media(source)

    if media is None:
        return False

    status_message = await message.reply(Reply.AUDIO_START_TEXT)

    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        input_path = directory / "source.media"
        output_path = directory / "output.ogg"

        downloaded = await _download_message_media(
            source,
            bot,
            input_path,
        )

        if not downloaded:
            await _show_failure(status_message)
            return True

        try:
            extracted = await _extract_audio(
                input_path,
                output_path,
            )
        except (OSError, ValueError):
            await _show_failure(status_message)
            return True

        if not extracted:
            await _show_failure(status_message)
            return True

        try:
            await message.reply_voice(
                voice=FSInputFile(str(output_path)),
            )
        except Exception:
            await _show_failure(status_message)
            return True

        try:
            await status_message.delete()
        except Exception:
            pass

    return True