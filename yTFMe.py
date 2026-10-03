import os
import gc
import shutil
import asyncio
from typing import List, Dict, Any, Tuple
import yt_dlp

import CAsh
import NAMe


async def process_and_send_media(
    bot,
    chat_id: int,
    thread_id: int,
    user_id: int,
    url: str,
    mode: str,
    start_reply_text: str,
    fail_reply_text: str
):
    if not await NAMe.queue_manager.acquire_slot(user_id):
        return

    sem = NAMe.queue_manager.get_semaphore(user_id)
    await sem.acquire()

    user_dir = f"downloads/{user_id}"
    os.makedirs(user_dir, exist_ok=True)

    try:
        ydl_opts_info = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }

        loop = asyncio.get_running_loop()

        def extract_info():
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, extract_info)
        if not info:
            await bot.send_message(chat_id, fail_reply_text, message_thread_id=thread_id)
            return

        items = []
        if "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if entry:
                    items.append(entry)
        else:
            items.append(info)

        if not items:
            await bot.send_message(chat_id, fail_reply_text, message_thread_id=thread_id)
            return

        await bot.send_message(chat_id, start_reply_text, message_thread_id=thread_id)

        if mode == "voice":
            await _handle_voice_mode(bot, chat_id, thread_id, user_id, items, user_dir)
        else:
            await _handle_normal_mode(bot, chat_id, thread_id, user_id, items, user_dir)

    except Exception:
        await bot.send_message(chat_id, fail_reply_text, message_thread_id=thread_id)
    finally:
        sem.release()
        NAMe.queue_manager.release_slot(user_id)
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir, ignore_errors=True)
        gc.collect()


async def _handle_voice_mode(
    bot,
    chat_id: int,
    thread_id: int,
    user_id: int,
    items: List[Dict[str, Any]],
    user_dir: str
):
    loop = asyncio.get_running_loop()

    for item in items:
        item_id = str(item.get("id") or item.get("url"))
        cached_file_id = await CAsh.get_cached_file_id(item_id, "voice")

        if cached_file_id:
            await bot.send_voice(chat_id, cached_file_id, message_thread_id=thread_id)
            continue

        item_url = item.get("url") or item.get("webpage_url") or item_id
        download_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{user_dir}/temp_%(id)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
        }

        def download_item():
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                return ydl.extract_info(item_url, download=True)

        downloaded_info = await loop.run_in_executor(None, download_item)
        if not downloaded_info:
            continue

        downloaded_file = downloaded_info.get("_filename")
        if not downloaded_file or not os.path.exists(downloaded_file):
            continue

        output_ogg = f"{user_dir}/voice_{item_id}.ogg"
        ffmpeg_cmd = f'ffmpeg -y -i "{downloaded_file}" -c:a libopus "{output_ogg}"'

        proc = await asyncio.create_subprocess_shell(
            ffmpeg_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()

        if os.path.exists(downloaded_file):
            os.remove(downloaded_file)

        if os.path.exists(output_ogg):
            from aiogram.types import FSInputFile
            input_file = FSInputFile(output_ogg)
            sent_msg = await bot.send_voice(chat_id, input_file, message_thread_id=thread_id)
            if sent_msg and sent_msg.voice:
                await CAsh.save_cached_file_id(item_id, "voice", sent_msg.voice.file_id)
            if os.path.exists(output_ogg):
                os.remove(output_ogg)


async def _handle_normal_mode(
    bot,
    chat_id: int,
    thread_id: int,
    user_id: int,
    items: List[Dict[str, Any]],
    user_dir: str
):
    loop = asyncio.get_running_loop()
    prepared_documents: List[Tuple[str, Any, str]] = []

    for item in items:
        item_id = str(item.get("id") or item.get("url"))
        cached_file_id = await CAsh.get_cached_file_id(item_id, "normal")

        if cached_file_id:
            prepared_documents.append((item_id, cached_file_id, ""))
            continue

        item_url = item.get("url") or item.get("webpage_url") or item_id
        download_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": f"{user_dir}/%(id)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
        }

        def download_item():
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                return ydl.extract_info(item_url, download=True)

        downloaded_info = await loop.run_in_executor(None, download_item)
        if not downloaded_info:
            continue

        downloaded_file = downloaded_info.get("_filename")
        if not downloaded_file or not os.path.exists(downloaded_file):
            continue

        uploader = downloaded_info.get("uploader") or ""
        title = downloaded_info.get("title") or "file"
        clean_name = NAMe.format_custom_filename(uploader, title)

        _, ext = os.path.splitext(downloaded_file)
        new_path = os.path.join(user_dir, f"{clean_name}{ext}")

        os.rename(downloaded_file, new_path)
        prepared_documents.append((item_id, new_path, clean_name))

    if not prepared_documents:
        return

    if len(prepared_documents) == 1:
        item_id, doc_source, clean_name = prepared_documents[0]
        if isinstance(doc_source, str) and os.path.exists(doc_source):
            from aiogram.types import FSInputFile
            input_file = FSInputFile(doc_source, filename=os.path.basename(doc_source))
            sent_msg = await bot.send_document(chat_id, input_file, message_thread_id=thread_id)
            if sent_msg and sent_msg.document:
                await CAsh.save_cached_file_id(item_id, "normal", sent_msg.document.file_id)
            if os.path.exists(doc_source):
                os.remove(doc_source)
        else:
            await bot.send_document(chat_id, doc_source, message_thread_id=thread_id)
    else:
        from aiogram.types import InputMediaDocument, FSInputFile

        batches = [prepared_documents[i:i + 8] for i in range(0, len(prepared_documents), 8)]

        for batch in batches:
            media_group = []
            file_handles = []

            for item_id, doc_source, clean_name in batch:
                if isinstance(doc_source, str) and os.path.exists(doc_source):
                    input_file = FSInputFile(doc_source, filename=os.path.basename(doc_source))
                    file_handles.append((item_id, doc_source))
                    media_group.append(InputMediaDocument(media=input_file))
                else:
                    media_group.append(InputMediaDocument(media=doc_source))

            sent_msgs = await bot.send_media_group(chat_id, media_group, message_thread_id=thread_id)

            for idx, (item_id, doc_source, clean_name) in enumerate(batch):
                if idx < len(sent_msgs) and sent_msgs[idx].document:
                    await CAsh.save_cached_file_id(item_id, "normal", sent_msgs[idx].document.file_id)

            for item_id, file_path in file_handles:
                if os.path.exists(file_path):
                    os.remove(file_path)
