import asyncio
import gc
import os
import subprocess

from yt_dlp import YoutubeDL


def cleanup_memory():
    gc.collect()


def _extract_and_download(
    url: str,
    out_template: str,
    mode: str = "normal",
) -> dict:
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
                    "-c:a",
                    "libopus",
                    "-f",
                    "ogg",
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
                    "-c",
                    "copy",
                ]
            },
            "quiet": True,
            "no_warnings": True,
        }

    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(
            url,
            download=True,
        )


async def extract_media_info(url: str) -> dict:
    def extract():
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }

        with YoutubeDL(options) as ydl:
            return ydl.extract_info(
                url,
                download=False,
            )

    loop = asyncio.get_running_loop()

    try:
        return await loop.run_in_executor(
            None,
            extract,
        )
    finally:
        cleanup_memory()


async def process_media_download(
    url: str,
    out_template: str,
    mode: str = "normal",
) -> dict:
    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(
            None,
            _extract_and_download,
            url,
            out_template,
            mode,
        )

        return info
    finally:
        cleanup_memory()


def get_entries(info: dict) -> list:
    if not info:
        return []

    entries = info.get("entries")

    if not entries:
        return []

    return [
        entry
        for entry in entries
        if entry
    ]


def get_entry_url(
    entry: dict,
    fallback_url: str,
) -> str:
    return (
        entry.get("webpage_url")
        or entry.get("original_url")
        or entry.get("url")
        or fallback_url
    )


def get_media_key(info: dict) -> str:
    if not info:
        return ""

    return (
        info.get("webpage_url")
        or info.get("original_url")
        or info.get("id")
        or info.get("url")
        or ""
    )


def convert_audio_to_voice_sync(
    input_path: str,
    output_path: str,
) -> str:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode == 0 and os.path.exists(output_path):
        return output_path

    return None


async def convert_audio_to_voice(
    input_path: str,
    target_dir: str,
) -> str:
    output_path = os.path.join(
        target_dir,
        "converted_voice.ogg",
    )

    loop = asyncio.get_running_loop()

    try:
        return await loop.run_in_executor(
            None,
            convert_audio_to_voice_sync,
            input_path,
            output_path,
        )
    finally:
        cleanup_memory()


def has_audio_stream(file_path: str) -> bool:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        file_path,
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        return bool(result.stdout.strip())
    except Exception:
        return False