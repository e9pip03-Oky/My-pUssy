import asyncio
import os

import yt_dlp

MAX_FILESIZE = 48 * 1024 * 1024

_FFMPEG = "ffmpeg"
_DEVNULL = asyncio.subprocess.DEVNULL


async def run_ffmpeg(args: list[str]) -> bool:
    cmd = [_FFMPEG, "-y", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=_DEVNULL,
        stderr=_DEVNULL,
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

    if crop_ratio != "none":
        try:
            r_w, r_h = map(int, crop_ratio.split(":"))

            if settings.get("landscape"):
                vf_parts.append(f"crop='iw':'iw*{r_h}/{r_w}'")
            elif settings.get("portrait"):
                vf_parts.append(f"crop='ih*{r_w}/{r_h}':'ih'")
            else:
                vf_parts.append(
                    f"crop='min(iw,ih*{r_w}/{r_h})':'min(ih,iw*{r_h}/{r_w})'"
                )
        except Exception:
            pass

    vf_parts.append("setsar=1")

    args = ["-i", in_path, "-an", "-c:v", "libx264"]
    if vf_parts:
        args.extend(["-vf", ",".join(vf_parts)])
    args.extend(_faststart_args(out_path))
    return await run_ffmpeg(args)


async def to_note_trim(
    in_path: str, out_path: str, start: str = "0", end: str | None = None
) -> bool:
    args = _trim_args(start, end)
    args.extend(
        [
            "-i",
            in_path,
            "-t",
            "60",
            "-vf",
            "crop='min(iw,ih)':'min(iw,ih)',scale=640:640,setsar=1",
            "-c:v",
            "libx264",
        ]
    )
    args.extend(_faststart_args(out_path))
    return await run_ffmpeg(args)


async def trim_video(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    args = _trim_args(start, end)
    args.extend(["-i", in_path, "-c:v", "libx264", "-c:a", "aac"])
    args.extend(_faststart_args(out_path))
    return await run_ffmpeg(args)


async def trim_voice(
    in_path: str, out_path: str, start: str, end: str | None = None
) -> bool:
    args = _trim_args(start, end)
    args.extend(["-i", in_path, "-c:a", "libopus", "-f", "ogg", out_path])
    return await run_ffmpeg(args)


async def to_voice(in_path: str, out_path: str) -> bool:
    return await run_ffmpeg(
        ["-i", in_path, "-vn", "-c:a", "libopus", "-f", "ogg", out_path]
    )


def _faststart_args(out_path: str) -> list[str]:
    return ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]


def _trim_args(start: str, end: str | None) -> list[str]:
    args = ["-ss", start]
    if end:
        args.extend(["-to", end])
    return args


async def download_merge(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download_merge, url, base)


async def download(url: str, base: str) -> tuple[dict, str]:
    return await asyncio.to_thread(_download, url, base)


async def get_entries(url: str) -> list[dict]:
    return await asyncio.to_thread(_extract_entries, url)


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