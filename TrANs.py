import logging
import re

from googletrans import Translator

log = logging.getLogger("voicebot")

UPPER_TARGETS = set("ATFGUJNMLБИА")


def has_formatting_chars(text: str) -> bool:
    return (
        any(char.upper() in UPPER_TARGETS for char in text)
        or "ss" in text.lower()
        or "h" in text.lower()
    )


def fix_format(text: str) -> str:
    result: list[str] = []
    previous = ""
    length = len(text)
    for index, char in enumerate(text):
        is_word_end = (index == length - 1) or not text[index + 1].isalnum()

        if char.lower() == "s":
            result.append("S" if previous == "s" else "s")
        elif char == "h" and is_word_end:
            result.append("H")
        elif char.upper() in UPPER_TARGETS:
            result.append(char.upper())
        elif "a" <= char.lower() <= "z" or "а" <= char.lower() <= "я":
            result.append(char.lower())
        else:
            result.append(char)

        if result:
            previous = result[-1]

    return "".join(result)


def make_name(info: dict) -> str:
    uploader = info.get("uploader") or info.get("channel") or ""
    publisher = re.sub(r"[^\w]", "", re.sub(r"\s+", "_", uploader.strip()))
    title = re.sub(
        r"\s+",
        " ",
        re.sub(r"[^\w\s]", "", (info.get("title") or "").strip()).replace("_", ""),
    ).strip()
    publisher = fix_format(publisher)
    title = fix_format(title)
    name = (
        f"{publisher} - {title}"
        if publisher and title
        else (title or publisher or "audio")
    )
    return name[:120].rstrip() or "audio"


async def process_translation(text: str, dest: str) -> str | None:
    try:
        async with Translator() as translator:
            response = await translator.translate(text, dest=dest)
            translated = response.text.replace(".", "").strip()
            return fix_format(translated)
    except Exception as exc:
        log.warning("translation failed: %s", exc)
        return None