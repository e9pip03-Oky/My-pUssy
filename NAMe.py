import re
from pathlib import Path


UPPER_EXCEPTIONS = set("ATFGUJNML")


def clean_name(value):
    value = value or ""

    value = re.sub(
        r"[^\w\s]",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    result = []

    for char in value:
        if char.isascii() and char.isalpha():
            if char.upper() in UPPER_EXCEPTIONS:
                result.append(char.upper())
            else:
                result.append(char.lower())
        else:
            result.append(char)

    return "".join(result)


def get_publisher(info):
    return clean_name(
        info.get("uploader")
        or info.get("channel")
        or ""
    )


def get_title(info):
    return clean_name(
        info.get("title")
        or info.get("id")
        or "media"
    )


def build_filename(info, extension):
    publisher = get_publisher(info)
    title = get_title(info)

    if publisher and title:
        name = f"{publisher} - {title}"
    elif publisher:
        name = publisher
    else:
        name = title or "media"

    return f"{name}.{extension}"


def unique_filename(directory, filename):
    path = Path(directory) / filename

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    number = 2

    while True:
        candidate = (
            Path(directory)
            / f"{stem} {number}{suffix}"
        )

        if not candidate.exists():
            return candidate

        number += 1