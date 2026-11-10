import logging  
import re  
  
from googletrans import Translator  
  
log = logging.getLogger("voicebot")  
  
UPPER_TARGETS = set("ATFGUJNMLБИА")  
  
  
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