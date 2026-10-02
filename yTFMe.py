import asyncio
import gc
import os
from yt_dlp import YoutubeDL


def cleanup_memory():
    gc.collect()


def cleanup_file(file_path: str):
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    finally:
        cleanup_memory()


def _extract_and_download(url: str, out_template: str, mode: str = "normal") -> dict:
    if mode == "voice":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                }
            ],
            "postprocessor_args": {
                "ExtractAudio": [
                    "-c:a", "libopus",
                    "-f", "ogg",
                ]
            },
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [
                {
                    "key": "FFmpegMerger",
                }
            ],
            "postprocessor_args": {
                "merger": [
                    "-c", "copy",
                ]
            },
            "quiet": True,
            "no_warnings": True,
        }

    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


async def process_media_download(url: str, out_template: str, mode: str = "normal") -> dict:
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, _extract_and_download, url, out_template, mode)
        return info
    finally:
        cleanup_memory()
