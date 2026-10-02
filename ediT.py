import asyncio
import os
import re
import subprocess
from collections import defaultdict
from aiogram import Bot
from aiogram.types import FSInputFile, Message
import CAsh
import NAMe
import Reply

USER_LOCKS = defaultdict(asyncio.Lock)


def parse_time_string(time_str: str) -> int:
    time_str = time_str.strip()
    if ":" in time_str:
        parts = time_str.split(":")
        minutes = int(parts[0])
        seconds = int(parts[1])
        return minutes * 60 + seconds
    else:
        return int(time_str)


def parse_time_range(input_text: str):
    text = input_text.strip()
    if text.startswith(Reply.VOICE_EDIT_TEXT):
        text = text[len(Reply.VOICE_EDIT_TEXT):].strip()

    pattern = r"^\s*(\d+(?::\d+)?)(?:\s+[/|-]\s+|\s+)(\d+(?::\d+)?)\s*$"
    match = re.match(pattern, text)

    if not match:
        return None, None

    start_raw, end_raw = match.groups()
    start_seconds = parse_time_string(start_raw)
    end_seconds = parse_time_string(end_raw)

    return start_seconds, end_seconds


def extract_voice_metadata(message: Message) -> dict:
    if message.voice:
        return {
            "file_id": message.voice.file_id,
            "file_unique_id": message.voice.file_unique_id,
            "duration": message.voice.duration,
            "file_size": message.voice.file_size,
            "mime_type": message.voice.mime_type,
            "from_user_id": message.from_user.id,
            "is_from_bot": message.from_user.is_bot
        }
    return None


async def store_voice_file_id(message_id: int, chat_id: int, user_id: int, file_id: str, is_bot: bool):
    await CAsh.save_voice_log(message_id, chat_id, user_id, file_id, is_bot)


async def retrieve_voice_file_id(message_id: int, chat_id: int) -> str:
    return await CAsh.get_voice_log(message_id, chat_id)


def get_audio_duration(file_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def cut_audio_stream(input_path: str, output_path: str, start_time: int, end_time: int = None) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", str(start_time)]
    if end_time is not None:
        cmd.extend(["-to", str(end_time)])
    cmd.extend(["-i", input_path, "-c", "copy", output_path])

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False


async def async_cut_audio_stream(input_path: str, output_path: str, start_time: int, end_time: int = None) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        cut_audio_stream,
        input_path,
        output_path,
        start_time,
        end_time
    )


async def handle_voice_edit_request(message: Message, bot: Bot) -> bool:
    if not message.reply_to_message:
        return False

    if not message.text or Reply.VOICE_EDIT_TEXT not in message.text:
        return False

    start_sec, end_sec = parse_time_range(message.text)
    if start_sec is None or end_sec is None:
        return False

    user_id = message.from_user.id

    async with USER_LOCKS[user_id]:
        replied_msg = message.reply_to_message
        file_id = None

        if replied_msg.voice:
            file_id = replied_msg.voice.file_id
        else:
            file_id = await retrieve_voice_file_id(replied_msg.message_id, message.chat.id)

        if not file_id:
            return False

        chat_id = message.chat.id
        thread_id = message.message_thread_id

        cache_key = f"{file_id}:{start_sec}:{end_sec}"
        cached_edited_file_id = await CAsh.get_cached_file(cache_key, "edited_voice")

        if cached_edited_file_id:
            sent_msg = await bot.send_voice(
                chat_id=chat_id,
                voice=cached_edited_file_id,
                reply_to_message_id=message.message_id
            )
            await store_voice_file_id(
                message_id=sent_msg.message_id,
                chat_id=chat_id,
                user_id=bot.id,
                file_id=sent_msg.voice.file_id,
                is_bot=True
            )
            return True

        with NAMe.auto_managed_download_dir(chat_id, user_id, thread_id) as download_dir:
            telegram_file = await bot.get_file(file_id)

            ext = os.path.splitext(telegram_file.file_path)[1]
            if not ext:
                ext = ".tmp"

            input_file_path = os.path.join(download_dir, f"input_voice{ext}")
            output_file_path = os.path.join(download_dir, "edited_voice.ogg")

            await bot.download_file(telegram_file.file_path, destination=input_file_path)

            success = await async_cut_audio_stream(input_file_path, output_file_path, start_sec, end_sec)

            if success and os.path.exists(output_file_path):
                edited_voice = FSInputFile(output_file_path)
                sent_msg = await bot.send_voice(
                    chat_id=chat_id,
                    voice=edited_voice,
                    reply_to_message_id=message.message_id
                )
                await CAsh.save_cached_file(cache_key, "edited_voice", sent_msg.voice.file_id)
                await store_voice_file_id(
                    message_id=sent_msg.message_id,
                    chat_id=chat_id,
                    user_id=bot.id,
                    file_id=sent_msg.voice.file_id,
                    is_bot=True
                )
                return True

        return False
