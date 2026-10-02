DB = None


def configure(sqlite3_module, db_path):
    global DB

    DB = sqlite3_module.connect(
        db_path,
        check_same_thread=False,
    )

    DB.execute("PRAGMA journal_mode=WAL")

    DB.execute(
        """
        CREATE TABLE IF NOT EXISTS file_cache (
            cache_key TEXT PRIMARY KEY,
            file_id TEXT NOT NULL
        )
        """
    )

    DB.execute(
        """
        CREATE TABLE IF NOT EXISTS album_cache (
            album_key TEXT PRIMARY KEY,
            items TEXT NOT NULL
        )
        """
    )

    DB.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            settings_key TEXT PRIMARY KEY,
            mode TEXT NOT NULL DEFAULT 'normal'
        )
        """
    )

    DB.commit()


def get_file_id(cache_key):
    row = DB.execute(
        """
        SELECT file_id
        FROM file_cache
        WHERE cache_key = ?
        """,
        (cache_key,),
    ).fetchone()

    return row[0] if row else None


def save_file_id(cache_key, file_id):
    DB.execute(
        """
        INSERT INTO file_cache (
            cache_key,
            file_id
        )
        VALUES (?, ?)
        ON CONFLICT(cache_key)
        DO UPDATE SET file_id = excluded.file_id
        """,
        (cache_key, file_id),
    )

    DB.commit()


def get_album(album_key, json_module):
    row = DB.execute(
        """
        SELECT items
        FROM album_cache
        WHERE album_key = ?
        """,
        (album_key,),
    ).fetchone()

    if not row:
        return None

    return json_module.loads(row[0])


def save_album(album_key, items, json_module):
    DB.execute(
        """
        INSERT INTO album_cache (
            album_key,
            items
        )
        VALUES (?, ?)
        ON CONFLICT(album_key)
        DO UPDATE SET items = excluded.items
        """,
        (
            album_key,
            json_module.dumps(
                items,
                ensure_ascii=False,
            ),
        ),
    )

    DB.commit()


def get_mode(settings_key):
    row = DB.execute(
        """
        SELECT mode
        FROM settings
        WHERE settings_key = ?
        """,
        (settings_key,),
    ).fetchone()

    return row[0] if row else "normal"


def save_mode(settings_key, mode):
    DB.execute(
        """
        INSERT INTO settings (
            settings_key,
            mode
        )
        VALUES (?, ?)
        ON CONFLICT(settings_key)
        DO UPDATE SET mode = excluded.mode
        """,
        (settings_key, mode),
    )

    DB.commit()