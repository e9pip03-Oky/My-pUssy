import asyncio  
import os  
  
import yt_dlp  
  
from cAsh import ffmpeg_semaphore  
  
MAX_FILESIZE = 439 * 1024 * 1024  
MAX_NOTE_FILESIZE = 439 * 1024 * 1024  
  
  
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
  
  
def _run_download(url: str, base: str, merge: bool) -> tuple[dict, str]:  
    options = {  
        "format": "bv+ba/b" if merge else "ba/b",  
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
    return await asyncio.to_thread(_run_download, url, base, False)  
  
  
async def download_merge(url: str, base: str) -> tuple[dict, str]:  
    return await asyncio.to_thread(_run_download, url, base, True)  
  
  
async def _run_ffmpeg(*args: str) -> bool:  
    async with ffmpeg_semaphore:  
        process = await asyncio.create_subprocess_exec(  
            "ffmpeg",  
            *args,  
            stdout=asyncio.subprocess.DEVNULL,  
            stderr=asyncio.subprocess.DEVNULL,  
        )  
        await process.wait()  
        return process.returncode == 0  
  
  
def _trim_args(start: str, end: str | None, in_path: str) -> list[str]:  
    args = ["-y", "-ss", start]  
    if end:  
        args.extend(["-to", end])  
    args.extend(["-i", in_path])  
    return args  
  
  
async def to_voice(in_path: str, out_path: str) -> bool:  
    return await _run_ffmpeg(  
        "-y", "-i", in_path, "-vn", "-c:a", "libopus", "-f", "ogg", out_path  
    )  
  
  
async def trim_voice(  
    in_path: str, out_path: str, start: str, end: str | None = None  
) -> bool:  
    args = _trim_args(start, end, in_path)  
    args.extend(["-c", "copy", out_path])  
    return await _run_ffmpeg(*args)  
  
  
async def trim_audio(  
    in_path: str, out_path: str, start: str, end: str | None = None  
) -> bool:  
    args = _trim_args(start, end, in_path)  
    args.extend(["-c", "copy", out_path])  
    return await _run_ffmpeg(*args)  
  
  
async def trim_note(  
    in_path: str, out_path: str, start: str, end: str | None = None  
) -> bool:  
    args = _trim_args(start, end, in_path)  
    args.extend(["-c:v", "libx264", "-c:a", "copy", out_path])  
    return await _run_ffmpeg(*args)  
  
  
async def trim_animation(  
    in_path: str, out_path: str, start: str, end: str | None = None  
) -> bool:  
    args = _trim_args(start, end, in_path)  
    args.extend(["-c", "copy", out_path])  
    return await _run_ffmpeg(*args)  
  
  
async def trim_video(  
    in_path: str, out_path: str, start: str, end: str | None = None  
) -> bool:  
    args = _trim_args(start, end, in_path)  
    args.extend(["-c", "copy", out_path])  
    return await _run_ffmpeg(*args)  
  
  
def _rotation_filters(settings: dict) -> list[str]:  
    filters: list[str] = []  
    if settings.get("flip_left") or settings.get("flip_right"):  
        filters.append("hflip")  
    double_rot = settings.get("double_rotate")  
    if settings.get("landscape"):  
        filters.append(  
            "transpose=1,transpose=1,transpose=1" if double_rot else "transpose=1"  
        )  
    elif settings.get("portrait"):  
        filters.append(  
            "transpose=2,transpose=2,transpose=2" if double_rot else "transpose=2"  
        )  
    return filters  
  
  
async def to_note_trim(  
    in_path: str,  
    out_path: str,  
    settings: dict | None = None,  
    start: str = "0",  
    end: str | None = None,  
) -> bool:  
    settings = settings or {}  
    filters = _rotation_filters(settings)  
    crop_align = settings.get("crop_align", "center")  
    y_expr = {  
        "bottom": "ih-min(iw\\,ih)",  
        "top": "0",  
    }.get(crop_align, "(ih-min(iw\\,ih))/2")  
    filters.append(f"crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:{y_expr}")  
    filters.append("scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2")  
    filters.append("scale=640:640,setsar=1/1")  
    args = _trim_args(start, end, in_path)  
    args.extend(["-t", "60", "-vf", ",".join(filters)])  
    if settings.get("muted"):  
        args.append("-an")  
    args.extend(["-c:v", "libx264", "-f", "mp4", out_path])  
    return await _run_ffmpeg(*args)  
  
  
async def to_animation(  
    in_path: str, out_path: str, settings: dict | None = None  
) -> bool:  
    settings = settings or {}  
    filters = _rotation_filters(settings)  
    crop_ratio = settings.get("crop_ratio", "none")  
    if crop_ratio != "none":  
        try:  
            ratio_w, ratio_h = map(int, crop_ratio.split(":"))  
            if ratio_w < ratio_h:  
                crop_w = f"ih*{ratio_w}/{ratio_h}"  
                crop_h = "ih"  
            else:  
                crop_w = "iw"  
                crop_h = f"iw*{ratio_h}/{ratio_w}"  
            filters.append(  
                f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:(ih-{crop_h})/2"  
            )  
        except Exception:  
            pass  
    filters.append("scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2")  
    args = ["-y", "-i", in_path, "-an", "-c:v", "libx264"]  
    if filters:  
        args.extend(["-vf", ",".join(filters)])  
    args.extend(["-f", "mp4", out_path])  
    return await _run_ffmpeg(*args)
