Path = None
SUBPROCESS = None
FFMPEG_PATH = ""


def configure(
    path_module,
    subprocess_module,
    ffmpeg_path,
):
    global Path
    global SUBPROCESS
    global FFMPEG_PATH

    Path = path_module
    SUBPROCESS = subprocess_module
    FFMPEG_PATH = ffmpeg_path


def base_options(workdir):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "outtmpl": str(
            Path(workdir) / "%(id)s.%(ext)s"
        ),
    }

    if FFMPEG_PATH:
        options["ffmpeg_location"] = FFMPEG_PATH

    return options


def extract_entries(yt_dlp, url):
    options = base_options(".")

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=False,
        )

    entries = info.get("entries")

    if not entries:
        return {
            "is_album": False,
            "album_identity": None,
            "entries": [info],
        }

    identity = (
        info.get("extractor_key")
        or info.get("extractor")
        or ""
    )

    playlist_id = (
        info.get("playlist_id")
        or info.get("id")
        or info.get("webpage_url")
        or url
    )

    return {
        "is_album": True,
        "album_identity": (
            f"{identity}:{playlist_id}"
        ),
        "entries": [
            entry
            for entry in entries
            if entry
        ],
    }


def entry_url(entry):
    return (
        entry.get("webpage_url")
        or entry.get("original_url")
        or entry.get("url")
    )


def download_one(
    yt_dlp,
    url,
    workdir,
    voice,
):
    options = base_options(workdir)

    options["noplaylist"] = True
    options["format"] = (
        "bestaudio"
        if voice
        else "bv+ba/b"
    )

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=True,
        )

    file_path = info.get("filepath")

    if file_path:
        path = Path(file_path)

        if path.exists():
            return info, path

    for item in info.get(
        "requested_downloads",
        [],
    ):
        file_path = item.get("filepath")

        if file_path:
            path = Path(file_path)

            if path.exists():
                return info, path

    raise FileNotFoundError(
        "Downloaded file was not found"
    )


def prepare_voice(source):
    source = Path(source)

    target = source.with_name(
        f"{source.stem}.voice.ogg"
    )

    command = [
        FFMPEG_PATH or "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-c:a",
        "libopus",
        "-f",
        "ogg",
        str(target),
    ]

    SUBPROCESS.run(
        command,
        check=True,
        stdout=SUBPROCESS.DEVNULL,
        stderr=SUBPROCESS.DEVNULL,
    )

    source.unlink()

    return target