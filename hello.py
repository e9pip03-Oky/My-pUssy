import asyncio
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile

import AUdio
import bToN
import CAsh
import ediT
import NAMe
import Reply
import yTFMe


BOT_TOKEN = os.getenv("BOT_TOKEN")

dp = Dispatcher()
bot = Bot(token=BOT_TOKEN)


async def send_takeoff_messages():
    takeoff_env = os.getenv("boT_TAkeoFF", "")

    if not takeoff_env.strip():
        return

    chat_ids = [
        cid.strip()
        for cid in takeoff_env.split("/")
        if cid.strip()
    ]

    for cid in chat_ids:
        try:
            owner_markup = bToN.get_owner_keyboard()

            await bot.send_message(
                chat_id=int(cid),
                text=Reply.TAKEOFF_TEXT,
                reply_markup=owner_markup,
            )
        except Exception:
            pass


async def is_admin_or_owner(
    message: types.Message,
) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True

    member = await message.bot.get_chat_member(
        message.chat.id,
        message.from_user.id,
    )

    return member.status in (
        "creator",
        "administrator",
    )


async def is_admin_or_owner_callback(
    callback: types.CallbackQuery,
) -> bool:
    if callback.message.chat.type == ChatType.PRIVATE:
        return True

    member = await callback.bot.get_chat_member(
        callback.message.chat.id,
        callback.from_user.id,
    )

    return member.status in (
        "creator",
        "administrator",
    )


def get_media_file_id(
    message: types.Message,
):
    if message.voice:
        return message.voice.file_id

    if message.audio:
        return message.audio.file_id

    if message.video:
        return message.video.file_id

    if message.video_note:
        return message.video_note.file_id

    if (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith(
            ("audio/", "video/")
        )
    ):
        return message.document.file_id

    return None


def is_supported_media(
    message: types.Message,
) -> bool:
    return get_media_file_id(message) is not None


async def has_audio_track(
    message: types.Message,
    download_dir: str,
) -> bool:
    downloaded_file = (
        await AUdio.extract_file_id_and_download(
            message,
            bot,
            download_dir,
        )
    )

    if not downloaded_file:
        return False

    return await yTFMe.has_audio_stream(
        downloaded_file,
    )


async def execute_trim_task(
    message: types.Message,
    replied_message: types.Message,
    start_sec: int,
    end_sec: int,
):
    chat_id = message.chat.id
    user_id = message.from_user.id
    thread_id = message.message_thread_id
    start_msg = None

    try:
        start_msg = await message.answer(
            Reply.DOWNLOAD_START_TEXT,
            reply_to_message_id=message.message_id,
        )

        with NAMe.auto_managed_download_dir(
            chat_id,
            user_id,
            thread_id,
        ) as download_dir:
            downloaded_path = (
                await AUdio.extract_file_id_and_download(
                    replied_message,
                    bot,
                    download_dir,
                )
            )

            if (
                not downloaded_path
                or not os.path.exists(downloaded_path)
            ):
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
                return

            if not await yTFMe.has_audio_stream(
                downloaded_path
            ):
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
                return

            trimmed_file_path = (
                ediT.process_audio_trim(
                    downloaded_path,
                    start_sec,
                    end_sec,
                )
            )

            if (
                not trimmed_file_path
                or not os.path.exists(trimmed_file_path)
            ):
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
                return

            media_file = FSInputFile(
                trimmed_file_path
            )

            if (
                replied_message.voice
                or replied_message.audio
            ):
                await bot.send_voice(
                    chat_id=chat_id,
                    voice=media_file,
                    reply_to_message_id=message.message_id,
                )
            else:
                await bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    reply_to_message_id=message.message_id,
                )

            await start_msg.delete()

    except asyncio.CancelledError:
        if start_msg is not None:
            try:
                await start_msg.delete()
            except Exception:
                pass

        raise

    except Exception:
        if start_msg is not None:
            try:
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
            except Exception:
                pass

    finally:
        yTFMe.cleanup_memory()


@dp.message(CommandStart())
async def start_handler(
    message: types.Message,
):
    await CAsh.add_user(
        message.from_user.id
    )


@dp.message(F.text == Reply.EDIT_COMMAND_TEXT)
async def edit_handler(
    message: types.Message,
):
    if not await is_admin_or_owner(message):
        return

    replied_message = message.reply_to_message

    if replied_message is None:
        return

    if not is_supported_media(replied_message):
        return

    user_id = message.from_user.id
    thread_id = message.message_thread_id

    with NAMe.auto_managed_download_dir(
        message.chat.id,
        user_id,
        thread_id,
    ) as download_dir:
        if not await has_audio_track(
            replied_message,
            download_dir,
        ):
            return

    CAsh.set_user_edit_waiting(
        user_id,
        replied_message,
    )

    await message.answer(
        text=Reply.EDIT_HELP_MESSAGE_TEXT,
        reply_markup=bToN.get_edit_help_keyboard(),
        reply_to_message_id=message.message_id,
    )


@dp.message(F.reply_to_message)
async def edit_duration_handler(
    message: types.Message,
):
    user_id = message.from_user.id
    waiting_message = CAsh.get_user_edit_waiting(
        user_id
    )

    if waiting_message is None:
        return

    if not message.text:
        return

    status, start_sec, end_sec = (
        ediT.parse_trim_input(message.text)
    )

    if status == "invalid_range":
        await message.answer(
            text=Reply.EDIT_INVALID_TIME_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id,
        )
        return

    if status == "invalid_format":
        await message.answer(
            text=Reply.EDIT_HELP_MESSAGE_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id,
        )
        return

    CAsh.clear_user_edit_waiting(user_id)

    asyncio.create_task(
        execute_trim_task(
            message,
            waiting_message,
            start_sec,
            end_sec,
        )
    )


@dp.callback_query(F.data == "set_mode_voice")
async def mode_voice_handler(
    callback: types.CallbackQuery,
):
    if not await is_admin_or_owner_callback(
        callback
    ):
        await callback.answer(
            text=Reply.NO_PERMISSION_ALERT,
            show_alert=True,
        )
        return

    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id

    current_mode = await CAsh.get_chat_mode(
        chat_id,
        thread_id,
    )

    new_mode = (
        "normal"
        if current_mode == "voice"
        else "voice"
    )

    await CAsh.set_chat_mode(
        chat_id,
        thread_id,
        new_mode,
    )

    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(
            new_mode
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "set_mode_normal")
async def mode_normal_handler(
    callback: types.CallbackQuery,
):
    if not await is_admin_or_owner_callback(
        callback
    ):
        await callback.answer(
            text=Reply.NO_PERMISSION_ALERT,
            show_alert=True,
        )
        return

    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id

    current_mode = await CAsh.get_chat_mode(
        chat_id,
        thread_id,
    )

    new_mode = (
        "voice"
        if current_mode == "normal"
        else "normal"
    )

    await CAsh.set_chat_mode(
        chat_id,
        thread_id,
        new_mode,
    )

    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(
            new_mode
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "show_edit_help")
async def show_edit_help_handler(
    callback: types.CallbackQuery,
):
    await callback.answer(
        text=Reply.EDIT_HELP_POPUP_TEXT,
        show_alert=True,
    )


async def process_start_media(
    message: types.Message,
):
    replied_message = message.reply_to_message

    if replied_message is None:
        return

    if not is_supported_media(
        replied_message
    ):
        return

    user_id = message.from_user.id

    if not CAsh.queue_manager.can_accept_request(
        user_id
    ):
        return

    CAsh.queue_manager.increment_user_count(
        user_id
    )

    semaphore = (
        CAsh.queue_manager.get_semaphore(
            user_id
        )
    )

    async def process():
        async with semaphore:
            chat_id = message.chat.id
            thread_id = message.message_thread_id
            start_msg = None

            try:
                start_msg = await message.answer(
                    Reply.CONVERT_START_TEXT,
                    reply_to_message_id=message.message_id,
                )

                with NAMe.auto_managed_download_dir(
                    chat_id,
                    user_id,
                    thread_id,
                ) as download_dir:
                    media_file_id = get_media_file_id(
                        replied_message
                    )

                    if not media_file_id:
                        await start_msg.edit_text(
                            Reply.DOWNLOAD_FAILED_TEXT
                        )
                        return

                    media_key = (
                        replied_message.file_unique_id
                    )

                    cached_file_id = (
                        await CAsh.get_cached_file(
                            media_key,
                            "voice",
                        )
                    )

                    if cached_file_id:
                        await bot.send_voice(
                            chat_id=chat_id,
                            voice=cached_file_id,
                            reply_to_message_id=message.message_id,
                        )
                        await start_msg.delete()
                        return

                    converted_voice_path = (
                        await AUdio.process_media_to_voice(
                            replied_message,
                            bot,
                            download_dir,
                        )
                    )

                    if (
                        not converted_voice_path
                        or not os.path.exists(
                            converted_voice_path
                        )
                    ):
                        await start_msg.edit_text(
                            Reply.DOWNLOAD_FAILED_TEXT
                        )
                        return

                    sent_voice = await bot.send_voice(
                        chat_id=chat_id,
                        voice=FSInputFile(
                            converted_voice_path
                        ),
                        reply_to_message_id=message.message_id,
                    )

                    await CAsh.save_cached_file(
                        media_key,
                        "voice",
                        sent_voice.voice.file_id,
                    )

                    await start_msg.delete()

            except Exception:
                if start_msg is not None:
                    try:
                        await start_msg.edit_text(
                            Reply.DOWNLOAD_FAILED_TEXT
                        )
                    except Exception:
                        pass

            finally:
                CAsh.queue_manager.decrement_user_count(
                    user_id
                )
                yTFMe.cleanup_memory()

    asyncio.create_task(process())


@dp.message(F.text == Reply.START_AUDIO_TRIGGER_TEXT)
async def audio_convert_reply_handler(
    message: types.Message,
):
    if not message.reply_to_message:
        return

    await process_start_media(message)


@dp.message(
    F.text.contains("http://")
    | F.text.contains("https://")
)
async def media_download_handler(
    message: types.Message,
):
    if NAMe.is_telegram_url(
        message.text.strip()
    ):
        return

    user_id = message.from_user.id

    if not CAsh.queue_manager.can_accept_request(
        user_id
    ):
        return

    CAsh.queue_manager.increment_user_count(
        user_id
    )

    semaphore = (
        CAsh.queue_manager.get_semaphore(
            user_id
        )
    )

    async def process():
        async with semaphore:
            await process_url_download(
                message
            )

            CAsh.queue_manager.decrement_user_count(
                user_id
            )
            yTFMe.cleanup_memory()

    asyncio.create_task(process())


async def process_url_download(
    message: types.Message,
):
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    url = message.text.strip()

    current_mode = await CAsh.get_chat_mode(
        chat_id,
        thread_id,
    )

    start_msg = None

    try:
        start_msg = await message.answer(
            Reply.DOWNLOAD_START_TEXT,
            reply_to_message_id=message.message_id,
        )

        with NAMe.auto_managed_download_dir(
            chat_id,
            user_id,
            thread_id,
        ) as download_dir:
            await yTFMe.process_media_download(
                url,
                os.path.join(
                    download_dir,
                    "%(title)s.%(ext)s",
                ),
                current_mode,
            )

            file_paths = (
                NAMe.get_downloaded_file_paths(
                    download_dir
                )
            )

            if not file_paths:
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
                return

            if current_mode == "voice":
                for file_path in file_paths:
                    await bot.send_voice(
                        chat_id=chat_id,
                        voice=FSInputFile(file_path),
                        reply_to_message_id=message.message_id,
                    )
            else:
                if not NAMe.is_album(file_paths):
                    file_path = NAMe.get_single_file(
                        file_paths
                    )

                    await bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(file_path),
                        reply_to_message_id=message.message_id,
                    )
                else:
                    for batch in NAMe.get_album_batches(
                        file_paths
                    ):
                        media_group = [
                            types.InputMediaDocument(
                                media=FSInputFile(
                                    file_path
                                )
                            )
                            for file_path in batch
                        ]

                        await bot.send_media_group(
                            chat_id=chat_id,
                            media=media_group,
                            reply_to_message_id=message.message_id,
                        )

            await start_msg.delete()

    except Exception:
        if start_msg is not None:
            try:
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT
                )
            except Exception:
                pass


@dp.message(F.chat.type == ChatType.PRIVATE)
async def private_messages_handler(
    message: types.Message,
):
    if message.text and (
        message.text.startswith("/")
        or "http" in message.text
    ):
        return

    if (
        message.text
        and CAsh.get_user_edit_waiting(
            message.from_user.id
        ) is not None
    ):
        return

    user_id = message.from_user.id

    response_text = (
        await CAsh.get_next_rotating_response(
            user_id,
            Reply.ROTATING_RESPONSES,
        )
    )

    owner_markup = bToN.get_owner_keyboard()

    await message.answer(
        text=response_text,
        reply_markup=owner_markup,
        reply_to_message_id=message.message_id,
    )


@dp.message(
    F.chat.type.in_(
        {
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        }
    )
)
async def group_messages_handler(
    message: types.Message,
):
    if (
        message.text
        and message.text.strip()
        == Reply.BOT_TRIGGER_TEXT
    ):
        response_text = (
            await CAsh.get_next_rotating_response(
                message.from_user.id,
                Reply.ROTATING_RESPONSES,
            )
        )

        owner_markup = bToN.get_owner_keyboard()

        await message.answer(
            text=response_text,
            reply_markup=owner_markup,
            reply_to_message_id=message.message_id,
        )


async def main():
    await CAsh.init_db()
    await send_takeoff_messages()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main)