import asyncio
import os

import yt_dlp

MAX_FILESIZE = 48 * 1024 * 1024
MAX_NOTE_FILESIZE = 20 * 1024 * 1024


def _extract_entries(url: str) -> list[dict]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if "entries" in info:
        return [entry for entry in info["entries"] if entry]
    return [info]


def _download(url: str, base: str) -> tuple[dict, str]:
    options = {
        "format": "ba/b",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILESIZE,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > MAX_FILESIZE:
                raise RuntimeError(f"file too large: {size}")
        return info, path


def _download_merge(url: str, base: str) -> tuple[dict, str]:
    options = {
        "format": "bv+ba/b",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILESIZE,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > MAX_FILESIZE:
                raise RuntimeError(f"file too large: {size}")
        return info, path


async def get_entries(url: str) -> list[dict]:
    return await asyncio.to_thread(_extract_entries, url)


async def download(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download, url, base)


async def download_merge(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download_merge, url, base)


async def _run_ffmpeg(*args: str) -> bool:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()
    return process.returncode == 0


async def _probe_dimensions(in_path: str) -> tuple[int, int]:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        in_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    try:
        width_str, height_str = stdout.decode().strip().split(",")
        return int(width_str), int(height_str)
    except Exception:
        return 0, 0


async def to_voice(in_path: str, out_path: str) -> bool:
    return await _run_ffmpeg(
        "-y", "-i", in_path, "-vn", "-c:a", "libopus", "-f", "ogg", out_path
    )


async def trim_voice(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    args = ["-y", "-ss", start]
    if end:
        args.extend(["-to", end])
    args.extend(["-i", in_path, "-c:a", "libopus", "-f", "ogg", out_path])
    return await _run_ffmpeg(*args)


async def to_note_trim(
    in_path: str, out_path: str, start: str = "0", end: str | None = None
) -> bool:
    args = ["-y", "-ss", start]
    if end:
        args.extend(["-to", end])
    args.extend(
        [
            "-i",
            in_path,
            "-t",
            "60",
            "-vf",
            "crop='min(iw,ih)':'min(iw,ih)',scale=640:640,setsar=1/1",
            "-c:v",
            "libx264",
            "-movflags",
            "+faststart",
            out_path,
        ]
    )
    return await _run_ffmpeg(*args)


async def trim_video(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    args = ["-y", "-ss", start]
    if end:
        args.extend(["-to", end])
    args.extend(
        ["-i", in_path, "-c:v", "libx264", "-movflags", "+faststart", out_path]
    )
    return await _run_ffmpeg(*args)


async def to_sticker(
    in_path: str, out_path: str, settings: dict | None = None
) -> bool:
    settings = settings or {}
    filters: list[str] = []

    crop_ratio = settings.get("crop_ratio", "none")
    if crop_ratio != "none":
        try:
            ratio_w, ratio_h = map(int, crop_ratio.split(":"))
            if ratio_w < ratio_h:
                filters.append(f"crop='ih*{ratio_w}/{ratio_h}':'ih'")
            else:
                filters.append(f"crop='iw':'iw*{ratio_h}/{ratio_w}'")
        except Exception:
            pass

    double_rot = settings.get("double_rotate")
    if settings.get("landscape"):
        if double_rot:
            filters.append("transpose=1,transpose=1,transpose=1")
        else:
            filters.append("transpose=1")
    elif settings.get("portrait"):
        if double_rot:
            filters.append("transpose=2,transpose=2,transpose=2")
        else:
            filters.append("transpose=2")
    elif settings.get("force_portrait"):
        width, height = await _probe_dimensions(in_path)
        if width > height:
            if double_rot:
                filters.append("transpose=1,transpose=1,transpose=1")
            else:
                filters.append("transpose=1")

    if settings.get("flip_left") or settings.get("flip_right"):
        filters.append("hflip")

    args = ["-y", "-i", in_path, "-an", "-c:v", "libx264"]
    if filters:
        args.extend(["-vf", ",".join(filters)])
    args.extend(["-movflags", "+faststart", out_path])

    return await _run_ffmpeg(*args)