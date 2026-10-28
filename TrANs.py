import logging
import re

from googletrans import Translator

log = logging.getLogger("voicebot")

UPPER_TARGETS = set("ATFGUJNMLБИА")


def has_formatting_chars(text: str) -> bool:
    return any(c.upper() in UPPER_TARGETS for c in text) or "ss" in text.lower()


def fix_format(text: str) -> str:
    res = []
    prev_char = ""
    for char in text:
        if char == "s" and prev_char == "s":
            res.append("S")
        elif char.upper() in UPPER_TARGETS:
            res.append(char.upper())
        elif "a" <= char.lower() <= "z" or "а" <= char.lower() <= "я":
            res.append(char.lower())
        else:
            res.append(char)
        prev_char = char
    return "".join(res)


def make_name(info: dict) -> str:
    uploader = info.get("uploader") or info.get("channel") or ""
    pub = re.sub(r"[^\w]", "", re.sub(r"\s+", "_", uploader.strip()))
    title = re.sub(
        r"\s+",
        " ",
        re.sub(r"[^\w\s]", "", (info.get("title") or "").strip()).replace("_", ""),
    ).strip()
    pub = fix_format(pub)
    title = fix_format(title)
    name = f"{pub} - {title}" if pub and title else (title or pub or "audio")
    return name[:120].rstrip() or "audio"


async def process_translation(text: str, dest: str) -> str | None:
    try:
        async with Translator() as translator:
            res = await translator.translate(text, dest=dest)
            translated = res.text.replace(".", "").strip()
            return fix_format(translated)
    except Exception as exc:
        log.warning("translation failed: %s", exc)
        return None