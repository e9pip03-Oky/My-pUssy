import asyncio
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InputMediaDocument

import AUdio
import CAsh
import Reply
import bToN
import ediT
import NAMe
import yTFMe


BOT_TOKEN = os.getenv("BOT_TOKEN")

dp = Dispatcher()
bot = Bot(token=BOT_TOKEN)


def get_media_file_id(message: types.Message) -> str:
    if message.voice:
        return message.voice.file_unique_id

    if message.audio:
        return message.audio.file_unique_id

    if message.video:
        return message.video.file_unique_id

    if message.video_note:
        return message.video_note.file_unique_id

    if message.document:
        return message.document.file_unique_id

    return None


def is_supported_media(message: types.Message) -> bool:
    if not message:
        return False

    if message.voice or message.audio:
        return True

    if message.video or message.video_note:
        return True

    if message.document and message.document.mime_type:
        return message.document.mime_type.startswith(
            ("audio/", "video/")
        )

    return False


async def send_takeoff_messages():
    takeoff_env = os.getenv("boT_TAkeoFF", "")

    if not takeoff_env.strip():
        return

    chat_ids = [
        chat_id.strip()
        for chat_id in takeoff_env.split("/")
        if chat_id.strip()
    ]

    for chat_id in chat_ids:
        try:
            owner_markup = bToN.get_owner_keyboard()

            await bot.send_message(
                chat_id=int(chat_id),
                text=Reply.TAKEOFF_TEXT,
                reply_markup=owner_markup,
            )
        except Exception:
            pass


async def is_admin_or_owner(message: types.Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True

    member = await message.bot.get_chat_member(
        message.chat.id,
        message.from_user.id,
    )

    return member.status in ("creator", "administrator")


async def is_admin_or_owner_callback(
    callback: types.CallbackQuery,
) -> bool:
    if callback.message.chat.type == ChatType.PRIVATE:
        return True

    member = await callback.bot.get_chat_member(
        callback.message.chat.id,
        callback.from_user.id,
    )

    return member.status in ("creator", "administrator")


async def has_audio_track(
    message: types.Message,
    download_dir: str,
) -> tuple[str, bool]:
    downloaded_path = await AUdio.extract_file_id_and_download(
        message,
        bot,
        download_dir,
    )

    if not downloaded_path or not os.path.exists(downloaded_path):
        return None, False

    return downloaded_path, yTFMe.has_audio_stream(downloaded_path)


@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await CAsh.add_user(message.from_user.id)


@dp.message(F.text == Reply.EDIT_COMMAND_TEXT)
@dp.message(Command("edit"))
async def edit_handler(message: types.Message):
    if not await is_admin_or_owner(message):
        return

    thread_id = message.message_thread_id
    current_mode = await CAsh.get_chat_mode(
        message.chat.id,
        thread_id,
    )

    await message.answer(
        text=Reply.EDIT_MESSAGE_TEXT,
        reply_markup=bToN.get_mode_keyboard(current_mode),
        reply_to_message_id=message.message_id,
    )


@dp.callback_query(F.data == "set_mode_voice")
async def mode_voice_handler(callback: types.CallbackQuery):
    if not await is_admin_or_owner_callback(callback):
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

    new_mode = "normal" if current_mode == "voice" else "voice"

    await CAsh.set_chat_mode(
        chat_id,
        thread_id,
        new_mode,
    )

    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(new_mode),
    )

    await callback.answer()


@dp.callback_query(F.data == "set_mode_normal")
async def mode_normal_handler(callback: types.CallbackQuery):
    if not await is_admin_or_owner_callback(callback):
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

    new_mode = "voice" if current_mode == "normal" else "normal"

    await CAsh.set_chat_mode(
        chat_id,
        thread_id,
        new_mode,
    )

    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(new_mode),
    )

    await callback.answer()


@dp.callback_query(F.data == "show_edit_help")
async def show_edit_help_handler(callback: types.CallbackQuery):
    await callback.answer(
        text=Reply.EDIT_HELP_POPUP_TEXT,
        show_alert=True,
    )


async def execute_trim_task(
    message: types.Message,
    start_sec: int,
    end_sec: int,
):
    replied_msg = message.reply_to_message
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id

    try:
        with NAMe.auto_managed_download_dir(
            chat_id,
            user_id,
            thread_id,
        ) as download_dir:
            downloaded_path, has_audio = await has_audio_track(
                replied_msg,
                download_dir,
            )

            if not downloaded_path or not has_audio:
                return

            start_msg = await message.answer(
                Reply.DOWNLOAD_START_TEXT,
                reply_to_message_id=message.message_id,
            )

            trimmed_file_path = ediT.process_audio_trim(
                downloaded_path,
                start_sec,
                end_sec,
            )

            if (
                not trimmed_file_path
                or not os.path.exists(trimmed_file_path)
            ):
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT,
                )
                return

            media_file = FSInputFile(trimmed_file_path)

            if replied_msg.voice or replied_msg.audio:
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
        raise
    except Exception:
        try:
            await start_msg.edit_text(
                Reply.DOWNLOAD_FAILED_TEXT,
            )
        except Exception:
            pass
    finally:
        CAsh.clear_user_wait_task(user_id)


@dp.message(
    F.reply_to_message
    & F.text.func(lambda text: ediT.is_edit_trigger(text))
)
async def trim_media_reply_handler(message: types.Message):
    replied_msg = message.reply_to_message

    if not is_supported_media(replied_msg):
        return

    user_id = message.from_user.id
    time_query = (
        message.text
        .replace(Reply.EDIT_TRIGGER_TEXT, "")
        .strip()
    )

    if not time_query:
        await message.answer(
            text=Reply.EDIT_HELP_MESSAGE_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id,
        )
        return

    status, start_sec, end_sec = ediT.parse_trim_input(
        time_query,
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

    task = asyncio.create_task(
        execute_trim_task(
            message,
            start_sec,
            end_sec,
        )
    )

    CAsh.register_user_wait_task(
        user_id,
        task,
    )


async def process_start_media(message: types.Message):
    replied_msg = message.reply_to_message
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id

    media_key = get_media_file_id(replied_msg)

    if not media_key:
        return

    cached_file_id = await CAsh.get_cached_file(
        media_key,
        "voice",
    )

    if cached_file_id:
        await bot.send_voice(
            chat_id=chat_id,
            voice=cached_file_id,
            reply_to_message_id=message.message_id,
        )
        return

    start_msg = await message.answer(
        Reply.CONVERT_START_TEXT,
        reply_to_message_id=message.message_id,
    )

    try:
        with NAMe.auto_managed_download_dir(
            chat_id,
            user_id,
            thread_id,
        ) as download_dir:
            downloaded_file = await AUdio.process_media_to_voice(
                replied_msg,
                bot,
                download_dir,
            )

            if (
                not downloaded_file
                or not os.path.exists(downloaded_file)
            ):
                await start_msg.edit_text(
                    Reply.DOWNLOAD_FAILED_TEXT,
                )
                return

            voice_file = FSInputFile(downloaded_file)

            sent_message = await bot.send_voice(
                chat_id=chat_id,
                voice=voice_file,
                reply_to_message_id=message.message_id,
            )

            if sent_message.voice:
                await CAsh.save_cached_file(
                    media_key,
                    "voice",
                    sent_message.voice.file_id,
                )

            await start_msg.delete()

    except Exception:
        await start_msg.edit_text(
            Reply.DOWNLOAD_FAILED_TEXT,
        )


@dp.message(F.text == Reply.START_AUDIO_TRIGGER_TEXT)
async def audio_convert_reply_handler(message: types.Message):
    if not message.reply_to_message:
        return

    if not is_supported_media(message.reply_to_message):
        return

    user_id = message.from_user.id

    if not CAsh.queue_manager.can_accept_request(user_id):
        return

    CAsh.queue_manager.increment_user_count(user_id)

    semaphore = CAsh.queue_manager.get_semaphore(user_id)

    async def process():
        async with semaphore:
            try:
                await process_start_media(message)
            finally:
                CAsh.queue_manager.decrement_user_count(user_id)

    asyncio.create_task(process())


async def send_normal_items(
    chat_id: int,
    reply_to_message_id: int,
    items: list[dict],
):
    for index in range(0, len(items), 8):
        batch = items[index:index + 8]

        media_group = []

        for item in batch:
            media_group.append(
                InputMediaDocument(
                    media=item["file_id"],
                )
            )

        sent_messages = await bot.send_media_group(
            chat_id=chat_id,
            media=media_group,
            reply_to_message_id=reply_to_message_id,
        )

        for item, sent_message in zip(
            batch,
            sent_messages,
        ):
            if sent_message.document:
                await CAsh.save_cached_file(
                    item["media_key"],
                    "normal",
                    sent_message.document.file_id,
                )


async def process_url_download(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    url = message.text.strip()

    if NAMe.is_telegram_url(url):
        return

    current_mode = await CAsh.get_chat_mode(
        chat_id,
        thread_id,
    )

    start_msg = await message.answer(
        Reply.DOWNLOAD_START_TEXT,
        reply_to_message_id=message.message_id,
    )

    try:
        if current_mode == "voice":
            with NAMe.auto_managed_download_dir(
                chat_id,
                user_id,
                thread_id,
            ) as download_dir:
                info = await yTFMe.extract_media_info(url)

                entries = yTFMe.get_entries(info)

                if not entries:
                    entries = [info]

                for entry in entries:
                    media_key = yTFMe.get_media_key(entry)

                    cached_file_id = await CAsh.get_cached_file(
                        media_key,
                        "voice",
                    )

                    if cached_file_id:
                        await bot.send_voice(
                            chat_id=chat_id,
                            voice=cached_file_id,
                            reply_to_message_id=message.message_id,
                        )
                        continue

                    item_url = yTFMe.get_entry_url(entry, url)

                    voice_path = await yTFMe.process_media_download(
                        item_url,
                        os.path.join(
                            download_dir,
                            "%(title)s.%(ext)s",
                        ),
                        "voice",
                    )

                    if isinstance(voice_path, dict):
                        file_path = NAMe.get_downloaded_file_path(
                            download_dir,
                        )
                    else:
                        file_path = voice_path

                    if (
                        not file_path
                        or not os.path.exists(file_path)
                    ):
                        continue

                    sent_message = await bot.send_voice(
                        chat_id=chat_id,
                        voice=FSInputFile(
                            file_path,
                            filename=NAMe.build_file_name(entry),
                        ),
                        reply_to_message_id=message.message_id,
                    )

                    if sent_message.voice:
                        await CAsh.save_cached_file(
                            media_key,
                            "voice",
                            sent_message.voice.file_id,
                        )

                    NAMe.cleanup_directory_tree(download_dir)

                    os.makedirs(
                        download_dir,
                        exist_ok=True,
                    )

        else:
            with NAMe.auto_managed_download_dir(
                chat_id,
                user_id,
                thread_id,
            ) as download_dir:
                info = await yTFMe.extract_media_info(url)
                entries = yTFMe.get_entries(info)

                if not entries:
                    entries = [info]

                items = []

                for entry in entries:
                    media_key = yTFMe.get_media_key(entry)

                    cached_file_id = await CAsh.get_cached_file(
                        media_key,
                        "normal",
                    )

                    if cached_file_id:
                        items.append(
                            {
                                "media_key": media_key,
                                "file_id": cached_file_id,
                            }
                        )
                        continue

                    item_url = yTFMe.get_entry_url(entry, url)

                    await yTFMe.process_media_download(
                        item_url,
                        os.path.join(
                            download_dir,
                            "%(title)s.%(ext)s",
                        ),
                        "normal",
                    )

                    file_path = NAMe.get_downloaded_file_path(
                        download_dir,
                    )

                    if (
                        not file_path
                        or not os.path.exists(file_path)
                    ):
                        continue

                    sent_message = await bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(
                            file_path,
                            filename=NAMe.build_file_name(entry),
                        ),
                        reply_to_message_id=message.message_id,
                    )

                    if sent_message.document:
                        await CAsh.save_cached_file(
                            media_key,
                            "normal",
                            sent_message.document.file_id,
                        )

                    items.append(
                        {
                            "media_key": media_key,
                            "file_id": sent_message.document.file_id,
                        }
                    )

                    NAMe.cleanup_directory_tree(download_dir)

                    os.makedirs(
                        download_dir,
                        exist_ok=True,
                    )

                cached_items = [
                    item
                    for item in items
                    if item["file_id"]
                ]

                if cached_items:
                    await send_normal_items(
                        chat_id,
                        message.message_id,
                        cached_items,
                    )

        await start_msg.delete()

    except Exception:
        await start_msg.edit_text(
            Reply.DOWNLOAD_FAILED_TEXT,
        )


@dp.message(F.text.contains("http://") | F.text.contains("https://"))
async def media_download_handler(message: types.Message):
    if NAMe.is_telegram_url(message.text.strip()):
        return

    user_id = message.from_user.id

    if not CAsh.queue_manager.can_accept_request(user_id):
        return

    CAsh.queue_manager.increment_user_count(user_id)

    semaphore = CAsh.queue_manager.get_semaphore(user_id)

    async def process():
        async with semaphore:
            try:
                await process_url_download(message)
            finally:
                CAsh.queue_manager.decrement_user_count(user_id)

    asyncio.create_task(process())


@dp.message(F.chat.type == ChatType.PRIVATE)
async def private_messages_handler(message: types.Message):
    if message.text and (
        message.text.startswith("/")
        or "http" in message.text
    ):
        return

    user_id = message.from_user.id

    response_text = await CAsh.get_next_rotating_response(
        user_id,
        Reply.ROTATING_RESPONSES,
    )

    owner_markup = bToN.get_owner_keyboard()

    await message.answer(
        text=response_text,
        reply_markup=owner_markup,
        reply_to_message_id=message.message_id,
    )


@dp.message(
    F.chat.type.in_(
        {ChatType.GROUP, ChatType.SUPERGROUP}
    )
)
async def group_messages_handler(message: types.Message):
    if (
        message.text
        and message.text.strip() == Reply.BOT_TRIGGER_TEXT
    ):
        response_text = await CAsh.get_next_rotating_response(
            message.from_user.id,
            Reply.ROTATING_RESPONSES,
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
    asyncio.run(main())