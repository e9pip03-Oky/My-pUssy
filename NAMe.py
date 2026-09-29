import re
from pathlib import Path
from urllib.parse import urlparse


BASE_FOLDER = Path("downloads")

BLOCKED_TELEGRAM_HOSTS = {
    "t.me",
    "telegram.me",
    "telegram.dog",
}


def initialize_base_folder() -> None:
    BASE_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )


def context_folder(
    context_id: int,
) -> Path:
    initialize_base_folder()

    folder = (
        BASE_FOLDER
        / str(abs(context_id))
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    return folder


def is_blocked_telegram_url(
    url: str,
) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    hostname = (
        parsed.hostname
        or ""
    ).lower().rstrip(".")

    if hostname in BLOCKED_TELEGRAM_HOSTS:
        return True

    return hostname.endswith(
        ".t.me"
    )


def extract_urls(
    text: str,
) -> list[str]:
    if not text:
        return []

    return re.findall(
        r"https?://[^\s<>]+",
        text,
        flags=re.IGNORECASE,
    )


def get_allowed_urls(
    text: str,
) -> list[str]:
    return [
        url
        for url in extract_urls(text)
        if not is_blocked_telegram_url(url)
    ]


def normalize_text(
    value: str,
) -> str:
    result = []

    uppercase_letters = set(
        "ATFGUJNML"
    )

    for char in value:
        if char.isascii() and char.isalpha():
            if char.upper() in uppercase_letters:
                result.append(
                    char.upper()
                )
            else:
                result.append(
                    char.lower()
                )
            continue

        if char in " _&-":
            result.append(char)

    return "".join(result)


def clean_name(
    value: str,
) -> str:
    value = normalize_text(value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip(
        " -_"
    )


def make_filename(
    publisher: str | None,
    channel: str | None,
    title: str,
    extension: str,
) -> str:
    owner = clean_name(
        publisher or channel or ""
    )

    title = clean_name(title)

    if owner and title:
        filename = (
            f"{owner} - {title}"
        )
    else:
        filename = owner or title

    extension = extension.lstrip(".")

    if extension:
        filename = (
            f"{filename}.{extension}"
        )

    return filename


def cleanup_file(
    file_path: str | Path | None,
) -> None:
    if not file_path:
        return

    path = Path(file_path)

    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass