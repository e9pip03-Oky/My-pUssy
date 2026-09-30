import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path


class DownloadError(RuntimeError):
    pass


def _run(command):
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode:
        raise DownloadError(
            result.stderr.strip()
            or "ffmpeg failed"
        )


def _extract(
    yt_dlp,
    url,
    options,
):
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            return downloader.extract_info(
                url,
                download=True,
            )
    except Exception as exc:
        raise DownloadError(
            str(exc)
        ) from exc


def inspect(
    yt_dlp,
    url,
):
    try:
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
            }
        ) as downloader:
            return downloader.extract_info(
                url,
                download=False,
            )
    except Exception as exc:
        raise DownloadError(
            str(exc)
        ) from exc


def entries(
    yt_dlp,
    url,
):
    info = inspect(
        yt_dlp,
        url,
    )

    if info.get("_type") == "playlist":
        return [
            item
            for item in info.get("entries", [])
            if item
        ]

    return [info]


def _download(
    yt_dlp,
    url,
    directory,
    stem,
    selector,
):
    template = str(
        directory / f"{stem}.%(ext)s"
    )

    info = _extract(
        yt_dlp,
        url,
        {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": selector,
            "outtmpl": template,
            "overwrites": True,
        },
    )

    files = [
        path
        for path in directory.glob(
            f"{stem}.*"
        )
        if path.is_file()
    ]

    if not files:
        raise DownloadError(
            "downloaded file was not found"
        )

    return files[0], info


def merge_copy(
    video,
    audio,
    output,
):
    _run([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        str(output),
    ])

    return output


def opus_ogg(
    audio,
    output,
):
    _run([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(audio),
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(output),
    ])

    return output


def download_normal(
    yt_dlp,
    url,
    directory,
    name,
):
    separate_directory = Path(
        tempfile.mkdtemp(
            prefix="separate_",
            dir=directory,
        )
    )

    try:
        try:
            video, video_info = _download(
                yt_dlp,
                url,
                separate_directory,
                "video",
                "bestvideo",
            )

            audio, _ = _download(
                yt_dlp,
                url,
                separate_directory,
                "audio",
                "bestaudio",
            )

            output = (
                directory
                / f"{name}{video.suffix}"
            )

            merge_copy(
                video,
                audio,
                output,
            )

            return output, video_info

        except DownloadError:
            pass

        combined, info = _download(
            yt_dlp,
            url,
            directory,
            "media",
            "best",
        )

        output = (
            directory
            / f"{name}{combined.suffix}"
        )

        if combined != output:
            if output.exists():
                output.unlink()
            combined.replace(output)

        return output, info

    finally:
        shutil.rmtree(
            separate_directory,
            ignore_errors=True,
        )


def download_voice(
    yt_dlp,
    url,
    directory,
    name,
):
    audio, info = _download(
        yt_dlp,
        url,
        directory,
        "audio",
        "bestaudio",
    )

    output = directory / f"{name}.ogg"

    try:
        opus_ogg(
            audio,
            output,
        )

        return output, info
    finally:
        audio.unlink(
            missing_ok=True
        )


async def download_normal_async(*args):
    return await asyncio.to_thread(
        download_normal,
        *args,
    )


async def download_voice_async(*args):
    return await asyncio.to_thread(
        download_voice,
        *args,
    )
