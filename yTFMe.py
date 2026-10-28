import asyncio
import os

import yt_dlp

MAX_FILESIZE = 48 * 1024 * 1024


def _extract_entries(url: str) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if "entries" in info:
        return [e for e in info["entries"] if e]
    return [info]


def _download(url: str, base: str) -> tuple[dict, str]:
    opts = {
        "format": "ba/b",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILESIZE,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        if os.path.exists(path) and os.path.getsize(path) > MAX_FILESIZE:
            raise RuntimeError(f"file too large: {os.path.getsize(path)}")
        return info, path


def _download_merge(url: str, base: str) -> tuple[dict, str]:
    opts = {
        "format": "bv+ba/b",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILESIZE,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        if os.path.exists(path) and os.path.getsize(path) > MAX_FILESIZE:
            raise RuntimeError(f"file too large: {os.path.getsize(path)}")
        return info, path


async def get_entries(url: str) -> list[dict]:
    return await asyncio.to_thread(_extract_entries, url)


async def download(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download, url, base)


async def download_merge(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download_merge, url, base)


async def to_voice(in_path: str, out_path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        in_path,
        "-vn",
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        out_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def trim_voice(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", start]
    if end:
        cmd.extend(["-to", end])
    cmd.extend(["-i", in_path, "-c:a", "libopus", "-f", "ogg", out_path])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def to_note_trim(
    in_path: str, out_path: str, start: str = "0", end: str | None = None
) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", start]
    if end:
        cmd.extend(["-to", end])
    cmd.extend(
        [
            "-i",
            in_path,
            "-t",
            "60",
            "-vf",
            "crop='min(iw,ih)':'min(iw,ih)',scale=640:640",
            "-c:v",
            "libx264",
            out_path,
        ]
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def trim_video(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", start]
    if end:
        cmd.extend(["-to", end])
    cmd.extend(
        [
            "-i",
            in_path,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            out_path,
        ]
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def to_sticker(
    in_path: str, out_path: str, settings: dict | None = None
) -> bool:
    settings = settings or {}
    vf_parts = []

    if settings.get("landscape"):
        vf_parts.append("transpose=1")
    elif settings.get("portrait"):
        vf_parts.append("transpose=2")

    if settings.get("flip_left") or settings.get("flip_right"):
        vf_parts.append("hflip")

    crop_ratio = settings.get("crop_ratio", "none")
    crop_type = settings.get("crop_type", "none")

    if crop_ratio != "none":
        try:
            r_w, r_h = map(int, crop_ratio.split(":"))
            if crop_type == "width":
                vf_parts.append(f"crop='iw':'iw*{r_h}/{r_w}'")
            elif crop_type == "length":
                vf_parts.append(f"crop='ih*{r_w}/{r_h}':'ih'")
            else:
                vf_parts.append(
                    f"crop='min(iw,ih*{r_w}/{r_h})':'min(ih,iw*{r_h}/{r_w})'"
                )
        except Exception:
            pass

    cmd = ["ffmpeg", "-y", "-i", in_path, "-an", "-c:v", "libx264"]
    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
    cmd.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0