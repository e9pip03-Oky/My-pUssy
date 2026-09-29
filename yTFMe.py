import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import yt_dlp


FFMPEG = os.getenv(
    "FFMPEG",
    "ffmpeg",
)


def _download(
    url: str,
    folder: Path,
    mode: str,
) -> dict[str, Any]:
    if mode == "voice":
        format_selector = "bestaudio/best"
    else:
        format_selector = (
            "bestvideo+bestaudio/best"
        )

    options: dict[str, Any] = {
        "format": format_selector,
        "outtmpl": str(
            folder / "%(id)s.%(ext)s"
        ),
        "noplaylist": False,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "windowsfilenames": False,
        "overwrites": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

    return info


async def download(
    url: str,
    folder: Path,
    mode: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _download,
        url,
        folder,
        mode,
    )


def find_downloaded_files(
    folder: Path,
) -> list[Path]:
    if not folder.exists():
        return []

    return [
        path
        for path in folder.iterdir()
        if path.is_file()
    ]


async def merge_copy(
    video_file: Path,
    audio_file: Path,
    output_file: Path,
) -> Path:
    command = [
        FFMPEG,
        "-y",
        "-i",
        str(video_file),
        "-i",
        str(audio_file),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        str(output_file),
    ]

    process = (
        await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )

    return_code = await process.wait()

    if return_code != 0:
        raise RuntimeError(
            "FFmpeg merge failed"
        )

    return output_file


async def convert_to_voice(
    input_file: Path,
    output_file: Path,
) -> Path:
    command = [
        FFMPEG,
        "-y",
        "-i",
        str(input_file),
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(output_file),
    ]

    process = (
        await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )

    return_code = await process.wait()

    if return_code != 0:
        raise RuntimeError(
            "FFmpeg voice conversion failed"
        )

    return output_file