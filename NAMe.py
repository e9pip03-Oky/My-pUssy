Path = None
RE = None
URLPARSE = None


def configure(path_module, regex_module, urlparse):
    global Path
    global RE
    global URLPARSE

    Path = path_module
    RE = regex_module
    URLPARSE = urlparse


def is_telegram_link(url):
    host = (
        URLPARSE(url).hostname or ""
    ).lower()

    return (
        host == "t.me"
        or host.endswith(".t.me")
        or host == "telegram.me"
        or host.endswith(".telegram.me")
        or host == "telegram.dog"
        or host.endswith(".telegram.dog")
    )


def get_download_dir(root, scope_id):
    path = Path(root) / str(scope_id)
    path.mkdir(
        parents=True,
        exist_ok=True,
    )
    return path


def clean_name(value):
    value = value or ""

    value = RE.sub(
        r"[^\w\s]",
        "",
        value,
        flags=RE.UNICODE,
    )

    value = RE.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    exceptions = set("ATFGUJNML")
    result = []

    for char in value:
        if "A" <= char <= "Z":
            if char in exceptions:
                result.append(char)
            else:
                result.append(char.lower())
        elif "a" <= char <= "z":
            result.append(char.lower())
        else:
            result.append(char)

    return "".join(result).strip()


def get_publisher(info):
    return clean_name(
        info.get("uploader")
        or info.get("channel")
        or info.get("playlist_uploader")
        or info.get("playlist_channel")
        or ""
    )


def build_filename(info, file_path):
    path = Path(file_path)

    publisher = get_publisher(info)
    title = clean_name(
        info.get("title")
        or info.get("fulltitle")
        or ""
    )

    if publisher and title:
        name = f"{publisher} - {title}"
    elif publisher:
        name = publisher
    elif title:
        name = title
    else:
        name = "media"

    return f"{name}{path.suffix}"


def rename_downloaded_file(info, file_path):
    path = Path(file_path)

    target = path.with_name(
        build_filename(
            info,
            path,
        )
    )

    if target == path:
        return target

    counter = 2

    while target.exists():
        target = path.with_name(
            f"{path.stem} {counter}{path.suffix}"
        )
        counter += 1

    path.rename(target)

    return target


def cleanup(path):
    if not path:
        return

    path = Path(path)

    if not path.exists():
        return

    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
        return

    for child in list(path.iterdir()):
        cleanup(child)

    try:
        path.rmdir()
    except OSError:
        pass