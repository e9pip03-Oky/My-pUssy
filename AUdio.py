import os

from aiogram import Bot
from aiogram.types import Message

import yTFMe


async def extract_file_id_and_download(
    message: Message,
    bot: Bot,
    target_dir: str,
) -> str:
    file_id = None

    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.video_note:
        file_id = message.video_note.file_id
    elif message.document and message.document.mime_type:
        if message.document.mime_type.startswith(
            ("audio/", "video/")
        ):
            file_id = message.document.file_id

    if not file_id:
        return None

    file_info = await bot.get_file(file_id)

    download_path = os.path.join(
        target_dir,
        os.path.basename(file_info.file_path),
    )

    await bot.download_file(
        file_info.file_path,
        download_path,
    )

    return download_path


async def process_media_to_voice(
    message: Message,
    bot: Bot,
    target_dir: str,
) -> str:
    downloaded_file = await extract_file_id_and_download(
        message,
        bot,
        target_dir,
    )

    if not downloaded_file:
        return None

    if not yTFMe.has_audio_stream(downloaded_file):
        return None

    return await yTFMe.convert_audio_to_voice(
        downloaded_file,
        target_dir,
    )