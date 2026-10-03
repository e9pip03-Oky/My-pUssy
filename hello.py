import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

import Reply
import CAsh
import bToN
import NAMe
import yTFMe

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def handle_start(message: Message):
    thread_id = message.message_thread_id if message.is_topic_message else 0
    btn_markup = bToN.get_next_takeoff_button()
    await message.answer(
        Reply.STARTUP_MESSAGE,
        reply_markup=btn_markup,
        message_thread_id=thread_id
    )


@dp.message(Command("edit"))
@dp.message(F.text.lower() == Reply.CMD_EDIT)
async def handle_edit_command(message: Message):
    if not await bToN.is_user_allowed_to_edit(message):
        return

    thread_id = message.message_thread_id if message.is_topic_message else 0
    keyboard = await bToN.get_edit_keyboard(message.chat.id, thread_id)
    await message.answer(
        Reply.EDIT_TEXT,
        reply_markup=keyboard,
        message_thread_id=thread_id
    )


@dp.callback_query(F.data.startswith("set_mode:"))
async def handle_mode_callback(callback: CallbackQuery):
    if not await bToN.is_user_admin(callback):
        await callback.answer(Reply.ADMIN_ALERT_TEXT, show_alert=True)
        return

    thread_id = callback.message.message_thread_id if callback.message.is_topic_message else 0
    await CAsh.toggle_chat_mode(callback.message.chat.id, thread_id)

    updated_keyboard = await bToN.get_edit_keyboard(callback.message.chat.id, thread_id)
    await callback.message.edit_reply_markup(reply_markup=updated_keyboard)
    await callback.answer()


@dp.message()
async def handle_all_messages(message: Message):
    if not message.text:
        return

    text = message.text.strip()
    thread_id = message.message_thread_id if message.is_topic_message else 0
    chat_type = message.chat.type

    if NAMe.is_telegram_link(text):
        if chat_type == "private":
            idx = await CAsh.get_next_user_index(
                message.from_user.id,
                len(Reply.ROTATING_REPLIES)
            )
            await message.answer(
                Reply.ROTATING_REPLIES[idx],
                message_thread_id=thread_id
            )
        return

    extracted_url = NAMe.extract_url(text)

    if extracted_url:
        mode = await CAsh.get_chat_mode(message.chat.id, thread_id)
        asyncio.create_task(
            yTFMe.process_and_send_media(
                bot=bot,
                chat_id=message.chat.id,
                thread_id=thread_id,
                user_id=message.from_user.id,
                url=extracted_url,
                mode=mode,
                start_reply_text=Reply.DOWNLOAD_START_REPLY,
                fail_reply_text=Reply.DOWNLOAD_FAIL_REPLY
            )
        )
        return

    if chat_type == "private":
        idx = await CAsh.get_next_user_index(
            message.from_user.id,
            len(Reply.ROTATING_REPLIES)
        )
        await message.answer(
            Reply.ROTATING_REPLIES[idx],
            message_thread_id=thread_id
        )
    elif text.lower() == Reply.CMD_BOT:
        idx = await CAsh.get_next_user_index(
            message.from_user.id,
            len(Reply.ROTATING_REPLIES)
        )
        await message.answer(
            Reply.ROTATING_REPLIES[idx],
            message_thread_id=thread_id
        )


async def main():
    await CAsh.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
