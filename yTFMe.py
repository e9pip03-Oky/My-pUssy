
import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

import bToN


@dataclass
class DownloadResult:
    path: Path
    info: dict


def _base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
    }

    ffmpeg_path = bToN.get_ffmpeg_path()

    if ffmpeg_path:
        options["ffmpeg_location"] = ffmpeg_path

    return options


def _extract_entries_sync(url):
    options = _base_options()
    options["extract_flat"] = True

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=False,
        )

    entries = info.get("entries")

    if entries is not None:
        return [
            entry
            for entry in entries
            if entry
        ]

    return [info]


async def get_entries(url):
    return await asyncio.to_thread(
        _extract_entries_sync,
        url,
    )


def entry_url(entry):
    return (
        entry.get("webpage_url")
        or entry.get("original_url")
        or entry.get("url")
    )


def entry_identity(entry):
    extractor = (
        entry.get("extractor_key")
        or entry.get("ie_key")
        or entry.get("extractor")
        or ""
    )

    identifier = entry.get("id")

    if identifier:
        return f"{extractor}:{identifier}"

    return entry_url(entry) or ""


def _find_downloaded_file(directory, info):
    requested = info.get(
        "requested_downloads"
    ) or []

    for item in requested:
        filepath = item.get("filepath")

        if filepath:
            path = Path(filepath)

            if path.exists():
                return path

    with yt_dlp.YoutubeDL(
        _base_options()
    ) as ydl:
        prepared = Path(
            ydl.prepare_filename(info)
        )

    if prepared.exists():
        return prepared

    identifier = info.get("id")

    if identifier:
        matches = list(
            Path(directory).glob(
                f"{identifier}.*"
            )
        )

        matches = [
            path
            for path in matches
            if not path.name.endswith(
                ".animation.mp4"
            )
            and not path.name.endswith(
                ".voice.ogg"
            )
        ]

        if matches:
            return matches[0]

    raise FileNotFoundError(
        "Downloaded file was not found"
    )


def _download_sync(
    url,
    mode,
    directory,
):
    options = _base_options()

    options["outtmpl"] = str(
        Path(directory)
        / "%(id)s.%(ext)s"
    )

    if mode == bToN.MODE_VOICE:
        options["format"] = "bestaudio/best"
    else:
        options["format"] = "bv+ba/b"

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

    path = _find_downloaded_file(
        directory,
        info,
    )

    return DownloadResult(
        path=path,
        info=info,
    )


def _ffprobe_path():
    configured_path = bToN.get_ffmpeg_path()

    if configured_path:
        path = Path(configured_path)

        if path.is_dir():
            sibling = path / "ffprobe"
        else:
            sibling = path.with_name("ffprobe")

        if sibling.is_file():
            return str(sibling)

    return shutil.which("ffprobe") or "ffprobe"


def _video_codec(path):
    result = subprocess.run(
        [
            _ffprobe_path(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    codec = result.stdout.strip()

    if not codec:
        raise ValueError(
            "Downloaded media has no video stream"
        )

    return codec


def _prepare_animation_sync(path):
    output = path.with_name(
        f"{path.stem}.animation.mp4"
    )

    ffmpeg_path = (
        bToN.get_ffmpeg_path()
        or "ffmpeg"
    )

    codec = _video_codec(path)

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
    ]

    if codec == "h264":
        command.extend(
            [
                "-c:v",
                "copy",
            ]
        )
    else:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
            ]
        )

    command.extend(
        [
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(output),
        ]
    )

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if (
        not output.is_file()
        or output.stat().st_size == 0
    ):
        raise RuntimeError(
            "FFmpeg did not create the animation file"
        )

    path.unlink()

    return output


def _prepare_voice_sync(path):
    output = path.with_name(
        f"{path.stem}.voice.ogg"
    )

    ffmpeg_path = (
        bToN.get_ffmpeg_path()
        or "ffmpeg"
    )

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(path),
        "-vn",
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(output),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    path.unlink()

    final_path = path.with_suffix(".ogg")

    output.rename(final_path)

    return final_path


async def download_one(
    url,
    mode,
    directory,
):
    directory = Path(directory)

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = await asyncio.to_thread(
        _download_sync,
        url,
        mode,
        directory,
    )

    if mode == bToN.MODE_VOICE:
        voice_path = await asyncio.to_thread(
            _prepare_voice_sync,
            result.path,
        )

        return DownloadResult(
            path=voice_path,
            info=result.info,
        )

    if mode == bToN.MODE_STICKER:
        animation_path = await asyncio.to_thread(
            _prepare_animation_sync,
            result.path,
        )

        return DownloadResult(
            path=animation_path,
            info=result.info,
        )

    return result


async def cut_voice(
    input_path,
    output_path,
    start,
    end,
):
    ffmpeg_path = (
        bToN.get_ffmpeg_path()
        or "ffmpeg"
    )

    process = await asyncio.create_subprocess_exec(
        ffmpeg_path,
        "-y",
        "-ss",
        str(start),
        "-i",
        str(input_path),
        "-to",
        str(end - start),
        "-c",
        "copy",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed"
        )
