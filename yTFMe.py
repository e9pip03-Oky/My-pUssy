import asyncio
import gc
import os
import subprocess
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


def convert_to_voice_ogg(input_path: str, output_path: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vn",
        "-c:a", "libopus",
        "-f", "ogg",
        output_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False


async def async_convert_to_voice_ogg(input_path: str, output_path: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        convert_to_voice_ogg,
        input_path,
        output_path
    )


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
