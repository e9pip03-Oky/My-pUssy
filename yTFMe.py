import asyncio
import os
import re

import yt_dlp

MAX_FILESIZE = 48 * 1024 * 1024
UPPER_LETTERS = set("ATFGUJNML")


def _fix_english_case(text: str) -> str:
    res = []
    for char in text:
        if "a" <= char.lower() <= "z":
            res.append(char.upper() if char.upper() in UPPER_LETTERS else char.lower())
        else:
            res.append(char)
    return "".join(res)


def make_name(info: dict) -> str:
    uploader = info.get("uploader") or info.get("channel") or ""
    pub = re.sub(r"[^\w]", "", re.sub(r"\s+", "_", uploader.strip()))
    title = re.sub(
        r"\s+",
        " ",
        re.sub(r"[^\w\s]", "", (info.get("title") or "").strip()).replace("_", ""),
    ).strip()

    pub, title = _fix_english_case(pub), _fix_english_case(title)
    name = f"{pub} - {title}" if pub and title else (title or pub or "audio")
    return name[:120].rstrip() or "audio"


def _extract_entries(url: str) -> list[dict]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "noplaylist": False}
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
        return info, ydl.prepare_filename(info)


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
        return info, ydl.prepare_filename(info)


async def get_entries(url: str) -> list[dict]:
    return await asyncio.to_thread(_extract_entries, url)


async def download(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download, url, base)


async def download_merge(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download_merge, url, base)


async def to_voice(in_path: str, workdir: str, name: str) -> str | None:
    out_path = os.path.join(workdir, f"{name}.ogg")
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
    return out_path if proc.returncode == 0 else None


async def to_note(in_path: str, out_path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", in_path,
        "-t", "60",
        "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=640:640",
        "-c:v", "libx264", "-c:a", "aac",
        out_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def trim_voice(in_path: str, out_path: str, start: str, end: str | None = None) -> bool:
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