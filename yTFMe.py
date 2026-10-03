import os
import shutil
import gc
import asyncio
import yt_dlp
from NAMe import format_title_case

BASE_DOWNLOAD_DIR = "downloads"

def get_target_dir(key: str, task_id: str) -> str:
    target_dir = os.path.join(BASE_DOWNLOAD_DIR, f"{key}_{task_id}")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir

def cleanup_dir(target_dir: str):
    if target_dir and os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir, ignore_errors=True)
        except Exception:
            pass
    gc.collect()

async def extract_info(url: str) -> dict:
    loop = asyncio.get_event_loop()
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True
    }
    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    try:
        return await loop.run_in_executor(None, _extract)
    except Exception:
        return {}

async def download_specific_items(url: str, mode: str, key: str, task_id: str, items: list) -> list:
    target_dir = get_target_dir(key, task_id)
    loop = asyncio.get_event_loop()

    items_str = ",".join(str(i) for i in items)

    if mode == "voice":
        out_template = os.path.join(target_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'playlist_items': items_str,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
            }],
            'postprocessor_args': {
                'ffmpeg': ['-c:a', 'libopus', '-f', 'ogg']
            }
        }
    else:
        out_template = os.path.join(target_dir, "%(uploader)s - %(title)s.%(ext)s")
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'playlist_items': items_str,
            'merge_output_format': None,
            'postprocessor_args': {
                'ffmpeg': ['-c', 'copy']
            }
        }

    def run_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    try:
        await loop.run_in_executor(None, run_download)
    except Exception:
        cleanup_dir(target_dir)
        return []

    if not os.path.exists(target_dir):
        return []

    downloaded_files = [
        os.path.join(target_dir, f)
        for f in os.listdir(target_dir)
        if os.path.isfile(os.path.join(target_dir, f))
    ]

    processed_files = []

    if mode == "voice":
        for file_path in downloaded_files:
            if file_path.endswith(('.opus', '.ogg')):
                processed_files.append(file_path)
    else:
        for file_path in downloaded_files:
            dir_name, file_name = os.path.split(file_path)
            name_part, ext_part = os.path.splitext(file_name)
            formatted_name = format_title_case(name_part) + ext_part
            if formatted_name != file_name:
                new_path = os.path.join(dir_name, formatted_name)
                try:
                    os.rename(file_path, new_path)
                    processed_files.append(new_path)
                except Exception:
                    processed_files.append(file_path)
            else:
                processed_files.append(file_path)

    processed_files.sort()
    return processed_files
