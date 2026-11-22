import logging
import os
import re
from typing import Final

from googletrans import Translator

log = logging.getLogger("voicebot")

UPPER_TARGETS: Final = set("ATFGUJNMLБИА")


def has_formatting_chars(text: str) -> bool:
    lower = text.lower()
    return (
        any(char.upper() in UPPER_TARGETS for char in text)
        or "ss" in lower
        or "h" in lower
    )


def fix_format(text: str) -> str:
    result: list[str] = []
    previous = ""
    length = len(text)
    for index, char in enumerate(text):
        is_word_end = (index == length - 1) or not text[index + 1].isalnum()
        lower = char.lower()

        if lower == "s":
            result.append("S" if previous == "s" else "s")
        elif char == "h" and is_word_end:
            result.append("H")
        elif lower == "d" and is_word_end:
            if len(result) >= 2 and result[-1].islower() and result[-2].islower():
                result.append("D")
            else:
                result.append(char)
        elif char.upper() in UPPER_TARGETS:
            result.append(char.upper())
        elif "a" <= lower <= "z" or "а" <= lower <= "я":
            result.append(lower)
        else:
            result.append(char)

        if result:
            previous = result[-1]

    return "".join(result)


def _clean_name_part(value: str, allowed_symbols: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip())
    allowed = re.escape(allowed_symbols)
    cleaned = re.sub(rf"[^\w\s{allowed}]", "", normalized)
    return re.sub(r"\s+", " ", cleaned).strip()


def make_name(info: dict) -> str:
    publisher = info.get("uploader") or info.get("channel") or ""
    title = info.get("title") or ""
    publisher = _clean_name_part(str(publisher), "_")
    title = _clean_name_part(str(title), "&_")
    publisher = fix_format(publisher)
    title = fix_format(title)
    name = f"{publisher} - {title}" if publisher and title else title or publisher
    return fix_format(name[:120].rstrip(" .")) or "media"


def make_message_name(message, media=None) -> str:
    origin = getattr(message, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None)
    origin_user = getattr(origin, "sender_user", None)
    publisher = (
        getattr(origin, "author_signature", None)
        or getattr(origin_user, "full_name", None)
        or getattr(origin_user, "first_name", None)
    )
    channel = (
        getattr(origin_chat, "title", None)
        or getattr(getattr(message, "forward_from_chat", None), "title", None)
    )
    if not channel and getattr(message.chat, "type", None) == "channel":
        channel = message.chat.title
    file_name = getattr(media, "file_name", None)
    file_title = os.path.splitext(file_name)[0] if file_name else ""
    title = message.caption or file_title
    return make_name({"uploader": publisher, "channel": channel, "title": title})


async def process_translation(text: str, dest: str) -> str | None:
    try:
        async with Translator() as translator:
            response = await translator.translate(text, dest=dest)
            translated = response.text.replace(".", "").strip()
            return fix_format(translated)
    except Exception as exc:
        log.warning("translation failed: %s", exc)
        return None
