import asyncio
import os
import re
import shutil
from contextlib import contextmanager

BASE_DIR = "downloads"
download_queue = asyncio.Queue()


def apply_custom_case(text: str) -> str:
    uppercase_targets = set("ATFGUJNML")
    result = []
    for char in text:
        if char.upper() in uppercase_targets:
            result.append(char.upper())
        else:
            result.append(char.lower())
    return "".join(result)


def build_file_name(info_dict: dict) -> str:
    uploader = info_dict.get("uploader") or info_dict.get("channel") or ""
    title = info_dict.get("title") or info_dict.get("id") or ""

    clean_uploader = re.sub(r"[^\w\s&\-]", "", uploader, flags=re.UNICODE)
    clean_title = re.sub(r"[^\w\s&\-]", "", title, flags=re.UNICODE)

    clean_uploader = re.sub(r"\s+", " ", clean_uploader).strip()
    clean_title = re.sub(r"\s+", " ", clean_title).strip()

    if clean_uploader and clean_title:
        combined_name = f"{clean_uploader} - {clean_title}"
    else:
        combined_name = clean_uploader or clean_title

    return apply_custom_case(combined_name)


def get_user_download_path(chat_id: int, user_id: int, topic_id: int = None) -> str:
    clean_chat_id = str(abs(chat_id))
    clean_user_id = str(user_id)

    if chat_id == user_id:
        target_dir = os.path.join(BASE_DIR, clean_user_id)
    else:
        if topic_id:
            target_dir = os.path.join(
                BASE_DIR,
                clean_chat_id,
                "topics",
                str(topic_id),
                clean_user_id
            )
        else:
            target_dir = os.path.join(
                BASE_DIR,
                clean_chat_id,
                clean_user_id
            )

    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def cleanup_directory_tree(target_dir: str):
    if not os.path.exists(target_dir):
        return

    shutil.rmtree(target_dir, ignore_errors=True)

    parent = os.path.dirname(target_dir)
    base_abs = os.path.abspath(BASE_DIR)

    while os.path.abspath(parent) != base_abs and os.path.exists(parent):
        try:
            if not os.listdir(parent):
                os.rmdir(parent)
                parent = os.path.dirname(parent)
            else:
                break
        except Exception:
            break


@contextmanager
def auto_managed_download_dir(chat_id: int, user_id: int, topic_id: int = None):
    path = get_user_download_path(chat_id, user_id, topic_id)
    try:
        yield path
    finally:
        cleanup_directory_tree(path)


def get_downloaded_file_path(download_dir: str) -> str:
    if not os.path.exists(download_dir):
        return None
    files = os.listdir(download_dir)
    if files:
        return os.path.join(download_dir, files[0])
    return None
