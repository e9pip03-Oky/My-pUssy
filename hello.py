import os
import gc
import uuid
import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, InputMediaDocument
)
from aiogram.enums import ChatType

from Reply import (
    EDIT_COMMAND, BOT_COMMAND, TEXT_EDIT_RESPONSE, TEXT_START_DOWNLOAD,
    TEXT_FAIL_DOWNLOAD, TEXT_ALERT_UNAUTHORIZED, TEXT_TAKEOFF, ROTATING_REPLIES
)
from CAsh import db
from bToN import btn_mgr
from NAMe import queue_mgr, is_telegram_link
from yTFMe import extract_info, download_specific_items, cleanup_dir, get_target_dir

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_chat_key(message: Message) -> str:
    chat = message.chat
    if chat.type == ChatType.PRIVATE:
        return f"user_{message.from_user.id}"
    elif message.is_topic_message and message.message_thread_id:
        return f"chat_{chat.id}_topic_{message.message_thread_id}"
    else:
        return f"chat_{chat.id}"

def get_chat_key_from_callback(callback: CallbackQuery) -> str:
    message = callback.message
    chat = message.chat
    if chat.type == ChatType.PRIVATE:
        return f"user_{callback.from_user.id}"
    elif message.is_topic_message and message.message_thread_id:
        return f"chat_{chat.id}_topic_{message.message_thread_id}"
    else:
        return f"chat_{chat.id}"

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

async def send_single_item_normal(message: Message, item) -> str:
    if item['type'] == 'id':
        msg = await message.reply_document(item['val'])
        return msg.document.file_id if msg and msg.document else None

    file_path = item['val']
    input_file = FSInputFile(file_path)
    msg = await message.reply_document(input_file)
    return msg.document.file_id if msg and msg.document else None

@dp.message(F.text == EDIT_COMMAND)
async def handle_edit(message: Message):
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if not await is_admin(message.chat.id, message.from_user.id):
            return

    key = get_chat_key(message)
    current_mode = db.get_mode(key)
    keyboard = btn_mgr.get_edit_keyboard(current_mode)
    await message.reply(TEXT_EDIT_RESPONSE, reply_markup=keyboard)

@dp.callback_query(F.data.in_(["mode_voice", "mode_normal"]))
async def handle_mode_callback(callback: CallbackQuery):
    message = callback.message
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if not await is_admin(message.chat.id, callback.from_user.id):
            await callback.answer(TEXT_ALERT_UNAUTHORIZED, show_alert=True)
            return

    key = get_chat_key_from_callback(callback)
    current_mode = db.get_mode(key)
    target_mode = callback.data.split("_")[1]

    if current_mode == target_mode:
        new_mode = "normal" if current_mode == "voice" else "voice"
    else:
        new_mode = target_mode

    db.set_mode(key, new_mode)
    new_keyboard = btn_mgr.get_edit_keyboard(new_mode)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
    except Exception:
        pass
    await callback.answer()

@dp.message(F.text == BOT_COMMAND)
async def handle_bot_keyword(message: Message):
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        idx = db.get_next_reply_index(message.from_user.id, len(ROTATING_REPLIES))
        reply_text = ROTATING_REPLIES[idx]
        keyboard = btn_mgr.get_rotating_button()
        await message.reply(reply_text, reply_markup=keyboard)

@dp.message(F.text.startswith("http://") | F.text.startswith("https://"))
async def handle_download(message: Message):
    url = message.text.strip()

    if is_telegram_link(url):
        idx = db.get_next_reply_index(message.from_user.id, len(ROTATING_REPLIES))
        reply_text = ROTATING_REPLIES[idx]
        keyboard = btn_mgr.get_rotating_button()
        await message.reply(reply_text, reply_markup=keyboard)
        return

    key = get_chat_key(message)

    if not await queue_mgr.can_accept_task(key):
        return

    accepted = await queue_mgr.register_task(key, url)
    if not accepted:
        return

    mode = db.get_mode(key)
    cached_map = db.get_cached_map(url, mode)

    task_id = str(uuid.uuid4())[:8]
    target_dir = get_target_dir(key, task_id)
    start_msg = None
    info = None
    entries = None
    new_files = None
    final_items = None

    try:
        if cached_map:
            cached_indices = sorted([int(k) for k in cached_map.keys()])
            final_items = [{'type': 'id', 'val': cached_map[str(idx)]} for idx in cached_indices]

            if mode == "voice":
                for item in final_items:
                    await message.reply_voice(item['val'])
            else:
                if len(final_items) == 1:
                    await message.reply_document(final_items[0]['val'])
                else:
                    chunk_size = 10
                    for i in range(0, len(final_items), chunk_size):
                        chunk = final_items[i:i + chunk_size]
                        media_group = [InputMediaDocument(media=c_item['val']) for c_item in chunk]
                        await message.reply_media_group(media=media_group)
            return

        start_msg = await message.reply(TEXT_START_DOWNLOAD)

        info = await extract_info(url)
        entries = info.get('entries') if info and 'entries' in info and info['entries'] else [info] if info else []

        if not entries:
            await message.reply(TEXT_FAIL_DOWNLOAD)
            return

        total_count = len(entries)
        missing_indices = list(range(1, total_count + 1))

        downloaded_files_map = {}
        if missing_indices:
            new_files = await download_specific_items(url, mode, key, task_id, missing_indices)
            for idx_1, item_index in enumerate(missing_indices):
                if idx_1 < len(new_files):
                    downloaded_files_map[str(item_index - 1)] = new_files[idx_1]

        final_items = []
        for idx_2 in range(total_count):
            s_idx = str(idx_2)
            if s_idx in downloaded_files_map:
                final_items.append({'type': 'file', 'val': downloaded_files_map[s_idx], 'index': s_idx})

        if not final_items:
            await message.reply(TEXT_FAIL_DOWNLOAD)
            return

        new_cached_entries = {}

        if mode == "voice":
            for item in final_items:
                input_file = FSInputFile(item['val'])
                msg = await message.reply_voice(input_file)
                if msg and msg.voice:
                    new_cached_entries[item['index']] = msg.voice.file_id
        else:
            if len(final_items) == 1:
                f_id = await send_single_item_normal(message, final_items[0])
                if f_id and final_items[0]['type'] == 'file':
                    new_cached_entries[final_items[0]['index']] = f_id
            else:
                chunk_size = 10
                for i in range(0, len(final_items), chunk_size):
                    chunk = final_items[i:i + chunk_size]
                    media_group = [InputMediaDocument(media=FSInputFile(c_item['val'])) for c_item in chunk]

                    sent_msgs = await message.reply_media_group(media=media_group)
                    for idx_3, s_msg in enumerate(sent_msgs):
                        c_item = chunk[idx_3]
                        if c_item['type'] == 'file' and s_msg and s_msg.document:
                            new_cached_entries[c_item['index']] = s_msg.document.file_id

        if new_cached_entries:
            db.update_cached_map(url, mode, new_cached_entries)

    except Exception:
        try:
            await message.reply(TEXT_FAIL_DOWNLOAD)
        except Exception:
            pass
    finally:
        if start_msg:
            try:
                await start_msg.delete()
            except Exception:
                pass
        await queue_mgr.release_task(key)
        cleanup_dir(target_dir)

        info = None
        entries = None
        new_files = None
        final_items = None
        gc.collect()

@dp.message(F.chat.type == ChatType.PRIVATE)
async def handle_private_rotating(message: Message):
    idx = db.get_next_reply_index(message.from_user.id, len(ROTATING_REPLIES))
    reply_text = ROTATING_REPLIES[idx]
    keyboard = btn_mgr.get_rotating_button()
    await message.reply(reply_text, reply_markup=keyboard)

async def send_takeoff_messages():
    raw_env = os.getenv("boT_TAkeoFF", "")
    if not raw_env:
        return
    target_ids = [id_str.strip() for id_str in raw_env.split("/") if id_str.strip()]
    for target_id in target_ids:
        try:
            keyboard = btn_mgr.get_rotating_button()
            await bot.send_message(int(target_id), TEXT_TAKEOFF, reply_markup=keyboard)
        except Exception:
            pass

async def main():
    await send_takeoff_messages()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
