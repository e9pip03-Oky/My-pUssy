import os
from aiogram import Bot
from aiogram.types import FSInputFile, Message
import CAsh
import ediT
import NAMe
import Reply
import yTFMe


def get_replied_media_file_id(message: Message):
    if not message.reply_to_message:
        return None

    replied = message.reply_to_message

    if replied.video:
        return replied.video.file_id
    if replied.audio:
        return replied.audio.file_id
    if replied.voice:
        return replied.voice.file_id
    if replied.video_note:
        return replied.video_note.file_id
    if replied.document:
        return replied.document.file_id

    return None


async def handle_audio_conversion_request(message: Message, bot: Bot) -> bool:
    if not message.reply_to_message:
        return False

    if not message.text or message.text.strip() != Reply.START_CONVERT_TEXT:
        return False

    file_id = get_replied_media_file_id(message)
    if not file_id:
        return False

    user_id = message.from_user.id

    async with ediT.USER_LOCKS[user_id]:
        chat_id = message.chat.id
        thread_id = message.message_thread_id

        cache_key = f"conv_voice:{file_id}"
        cached_voice_id = await CAsh.get_cached_file(cache_key, "voice")

        if cached_voice_id:
            sent_msg = await bot.send_voice(
                chat_id=chat_id,
                voice=cached_voice_id,
                reply_to_message_id=message.message_id
            )
            await ediT.store_voice_file_id(
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

            input_path = os.path.join(download_dir, f"input_media{ext}")
            output_path = os.path.join(download_dir, "output_voice.ogg")

            await bot.download_file(telegram_file.file_path, destination=input_path)

            success = await yTFMe.async_convert_to_voice_ogg(input_path, output_path)

            if success and os.path.exists(output_path):
                voice_file = FSInputFile(output_path)
                sent_msg = await bot.send_voice(
                    chat_id=chat_id,
                    voice=voice_file,
                    reply_to_message_id=message.message_id
                )
                await CAsh.save_cached_file(cache_key, "voice", sent_msg.voice.file_id)
                await ediT.store_voice_file_id(
                    message_id=sent_msg.message_id,
                    chat_id=chat_id,
                    user_id=bot.id,
                    file_id=sent_msg.voice.file_id,
                    is_bot=True
                )
                return True

        return False
