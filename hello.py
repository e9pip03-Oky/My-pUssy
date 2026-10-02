import asyncio
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
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
    if takeoff_env.strip():
        chat_ids = [cid.strip() for cid in takeoff_env.split("/") if cid.strip()]
        for cid in chat_ids:
            try:
                owner_markup = bToN.get_owner_keyboard()
                await bot.send_message(
                    chat_id=int(cid),
                    text=Reply.TAKEOFF_TEXT,
                    reply_markup=owner_markup
                )
            except Exception:
                pass


async def is_admin_or_owner(message: types.Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True

    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


async def is_admin_or_owner_callback(callback: types.CallbackQuery) -> bool:
    if callback.message.chat.type == ChatType.PRIVATE:
        return True

    member = await callback.bot.get_chat_member(callback.message.chat.id, callback.from_user.id)
    return member.status in ("creator", "administrator")


@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await CAsh.add_user(message.from_user.id)


@dp.message(F.text == Reply.EDIT_COMMAND_TEXT)
@dp.message(Command("edit"))
async def edit_handler(message: types.Message):
    if await is_admin_or_owner(message):
        thread_id = message.message_thread_id
        current_mode = await CAsh.get_chat_mode(message.chat.id, thread_id)
        await message.answer(
            text=Reply.EDIT_MESSAGE_TEXT,
            reply_markup=bToN.get_mode_keyboard(current_mode),
            reply_to_message_id=message.message_id
        )


@dp.callback_query(F.data == "set_mode_voice")
async def mode_voice_handler(callback: types.CallbackQuery):
    if not await is_admin_or_owner_callback(callback):
        await callback.answer(text=Reply.NO_PERMISSION_ALERT, show_alert=True)
        return

    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id

    current_mode = await CAsh.get_chat_mode(chat_id, thread_id)
    new_mode = "normal" if current_mode == "voice" else "voice"

    await CAsh.set_chat_mode(chat_id, thread_id, new_mode)
    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(new_mode)
    )
    await callback.answer()


@dp.callback_query(F.data == "set_mode_normal")
async def mode_normal_handler(callback: types.CallbackQuery):
    if not await is_admin_or_owner_callback(callback):
        await callback.answer(text=Reply.NO_PERMISSION_ALERT, show_alert=True)
        return

    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id

    current_mode = await CAsh.get_chat_mode(chat_id, thread_id)
    new_mode = "voice" if current_mode == "normal" else "normal"

    await CAsh.set_chat_mode(chat_id, thread_id, new_mode)
    await callback.message.edit_reply_markup(
        reply_markup=bToN.get_mode_keyboard(new_mode)
    )
    await callback.answer()


@dp.callback_query(F.data == "show_edit_help")
async def show_edit_help_handler(callback: types.CallbackQuery):
    await callback.answer(text=Reply.EDIT_HELP_POPUP_TEXT, show_alert=True)


async def execute_trim_task(message: types.Message, start_sec: int, end_sec: int):
    replied_msg = message.reply_to_message
    chat_id = message.chat.id
    user_id = message.from_user.id
    thread_id = message.message_thread_id

    start_msg = await message.answer(Reply.DOWNLOAD_START_TEXT, reply_to_message_id=message.message_id)

    try:
        with NAMe.auto_managed_download_dir(chat_id, user_id, thread_id) as download_dir:
            downloaded_path = await AUdio.extract_file_id_and_download(replied_msg, bot, download_dir)

            if not downloaded_path or not os.path.exists(downloaded_path):
                await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
                return

            trimmed_file_path = ediT.process_audio_trim(downloaded_path, start_sec, end_sec)

            if not trimmed_file_path or not os.path.exists(trimmed_file_path):
                await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
                return

            media_file = FSInputFile(trimmed_file_path)

            if replied_msg.voice or replied_msg.audio:
                await bot.send_voice(chat_id=chat_id, voice=media_file, reply_to_message_id=message.message_id)
            else:
                await bot.send_video(chat_id=chat_id, video=media_file, reply_to_message_id=message.message_id)

            await start_msg.delete()

    except asyncio.CancelledError:
        try:
            await start_msg.delete()
        except Exception:
            pass
        raise
    except Exception:
        await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
    finally:
        CAsh.clear_user_wait_task(user_id)


@dp.message(F.reply_to_message & F.text.func(lambda text: ediT.is_edit_trigger(text)))
async def trim_media_reply_handler(message: types.Message):
    user_id = message.from_user.id
    time_query = message.text.replace(Reply.EDIT_TRIGGER_TEXT, "").strip()

    if not time_query:
        await message.answer(
            text=Reply.EDIT_HELP_MESSAGE_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id
        )
        return

    status, start_sec, end_sec = ediT.parse_trim_input(time_query)

    if status == "invalid_range":
        await message.answer(
            text=Reply.EDIT_INVALID_TIME_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id
        )
        return
    elif status == "invalid_format":
        await message.answer(
            text=Reply.EDIT_HELP_MESSAGE_TEXT,
            reply_markup=bToN.get_edit_help_keyboard(),
            reply_to_message_id=message.message_id
        )
        return

    task = asyncio.create_task(execute_trim_task(message, start_sec, end_sec))
    CAsh.register_user_wait_task(user_id, task)


@dp.message(F.text == Reply.START_AUDIO_TRIGGER_TEXT)
async def audio_convert_reply_handler(message: types.Message):
    if not message.reply_to_message:
        return

    user_id = message.from_user.id
    if not CAsh.queue_manager.can_accept_request(user_id):
        return

    CAsh.queue_manager.increment_user_count(user_id)
    semaphore = CAsh.queue_manager.get_semaphore(user_id)

    async def process():
        async with semaphore:
            replied_msg = message.reply_to_message
            chat_id = message.chat.id
            thread_id = message.message_thread_id

            start_msg = await message.answer(Reply.CONVERT_START_TEXT, reply_to_message_id=message.message_id)

            try:
                with NAMe.auto_managed_download_dir(chat_id, user_id, thread_id) as download_dir:
                    converted_voice_path = await AUdio.process_media_to_voice(replied_msg, bot, download_dir)

                    if not converted_voice_path or not os.path.exists(converted_voice_path):
                        await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
                        return

                    voice_file = FSInputFile(converted_voice_path)
                    await bot.send_voice(chat_id=chat_id, voice=voice_file, reply_to_message_id=message.message_id)
                    await start_msg.delete()

            except Exception:
                await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
            finally:
                CAsh.queue_manager.decrement_user_count(user_id)

    asyncio.create_task(process())


@dp.message(F.text.contains("http://") | F.text.contains("https://"))
async def media_download_handler(message: types.Message):
    user_id = message.from_user.id
    if not CAsh.queue_manager.can_accept_request(user_id):
        return

    CAsh.queue_manager.increment_user_count(user_id)
    semaphore = CAsh.queue_manager.get_semaphore(user_id)

    async def process():
        async with semaphore:
            url = message.text.strip()
            chat_id = message.chat.id
            thread_id = message.message_thread_id

            current_mode = await CAsh.get_chat_mode(chat_id, thread_id)
            start_msg = await message.answer(Reply.DOWNLOAD_START_TEXT, reply_to_message_id=message.message_id)

            try:
                with NAMe.auto_managed_download_dir(chat_id, user_id, thread_id) as download_dir:
                    out_template = os.path.join(download_dir, "%(title)s.%(ext)s")
                    info = await yTFMe.process_media_download(url, out_template, current_mode)

                    file_path = NAMe.get_downloaded_file_path(download_dir)

                    if not file_path or not os.path.exists(file_path):
                        await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
                        return

                    custom_title = NAMe.build_file_name(info) if info else None
                    media_file = FSInputFile(file_path, filename=custom_title if custom_title else None)

                    if current_mode == "voice":
                        await bot.send_voice(chat_id=chat_id, voice=media_file, reply_to_message_id=message.message_id)
                    else:
                        await bot.send_video(chat_id=chat_id, video=media_file, reply_to_message_id=message.message_id)

                    await start_msg.delete()

            except Exception:
                await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)
            finally:
                CAsh.queue_manager.decrement_user_count(user_id)

    asyncio.create_task(process())


@dp.message(F.chat.type == ChatType.PRIVATE)
async def private_messages_handler(message: types.Message):
    if message.text and (message.text.startswith("/") or "http" in message.text):
        return

    user_id = message.from_user.id

    if await CAsh.should_respond_private(user_id):
        response_text = await CAsh.get_next_rotating_response(
            user_id, Reply.ROTATING_RESPONSES
        )
        owner_markup = bToN.get_owner_keyboard()
        await message.answer(
            text=response_text,
            reply_markup=owner_markup,
            reply_to_message_id=message.message_id
        )


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_messages_handler(message: types.Message):
    if message.text and message.text.strip() == Reply.BOT_TRIGGER_TEXT:
        response_text = await CAsh.get_next_rotating_response(
            message.from_user.id, Reply.ROTATING_RESPONSES
        )
        owner_markup = bToN.get_owner_keyboard()
        await message.answer(
            text=response_text,
            reply_markup=owner_markup,
            reply_to_message_id=message.message_id
        )


async def main():
    await CAsh.init_db()
    await send_takeoff_messages()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
