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


@dp.message(F.voice)
async def voice_tracker_handler(message: types.Message):
    await ediT.store_voice_file_id(
        message_id=message.message_id,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        file_id=message.voice.file_id,
        is_bot=message.from_user.is_bot
    )


@dp.message(F.reply_to_message & F.text.contains(Reply.VOICE_EDIT_TEXT))
async def voice_edit_handler(message: types.Message):
    await ediT.handle_voice_edit_request(message, bot)


@dp.message(F.reply_to_message)
async def audio_conversion_handler(message: types.Message):
    await AUdio.handle_audio_conversion_request(message, bot)


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


@dp.callback_query(F.data == "show_edit_guide")
async def show_edit_guide_handler(callback: types.CallbackQuery):
    await callback.answer(
        text=Reply.EDIT_GUIDE_ALERT_TEXT,
        show_alert=True
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


async def execute_download_job(message: types.Message, url: str):
    chat_id = message.chat.id
    user_id = message.from_user.id
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
                sent_msg = await bot.send_voice(chat_id=chat_id, voice=media_file, reply_to_message_id=message.message_id)
                await ediT.store_voice_file_id(
                    message_id=sent_msg.message_id,
                    chat_id=chat_id,
                    user_id=bot.id,
                    file_id=sent_msg.voice.file_id,
                    is_bot=True
                )
            else:
                await bot.send_video(chat_id=chat_id, video=media_file, reply_to_message_id=message.message_id)

            await start_msg.delete()

    except Exception:
        await start_msg.edit_text(Reply.DOWNLOAD_FAILED_TEXT)


@dp.message(F.text.contains("http://") | F.text.contains("https://"))
async def media_download_handler(message: types.Message):
    user_id = message.from_user.id
    url = message.text.strip()

    resources = NAMe.user_manager.get_user_resources(user_id)
    semaphore = resources["semaphore"]
    queue = resources["queue"]

    if semaphore.locked() and queue.full():
        return

    try:
        queue.put_nowait(url)
    except asyncio.QueueFull:
        return

    async with semaphore:
        target_url = await queue.get()
        try:
            await execute_download_job(message, target_url)
        finally:
            queue.task_done()


@dp.message(F.chat.type == ChatType.PRIVATE)
async def private_messages_handler(message: types.Message):
    if message.text and (message.text.startswith("/") or "http" in message.text):
        return

    response_text = await CAsh.get_next_rotating_response(
        message.from_user.id, Reply.ROTATING_RESPONSES
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
