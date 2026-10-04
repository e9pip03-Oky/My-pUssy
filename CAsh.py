import aiosqlite


DB = None


async def configure(db_path):
    global DB

    DB = await aiosqlite.connect(db_path)

    await DB.execute(
        "PRAGMA journal_mode=WAL"
    )

    await DB.execute("""
        CREATE TABLE IF NOT EXISTS file_cache (
            cache_key TEXT PRIMARY KEY,
            file_id TEXT NOT NULL
        )
    """)

    await DB.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            settings_key TEXT PRIMARY KEY,
            mode TEXT NOT NULL
        )
    """)

    await DB.commit()


async def get_file_id(key):
    async with DB.execute("""
        SELECT file_id
        FROM file_cache
        WHERE cache_key = ?
    """, (key,)) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return None

    return row[0]


async def save_file_id(key, file_id):
    await DB.execute("""
        INSERT INTO file_cache (
            cache_key,
            file_id
        )
        VALUES (?, ?)
        ON CONFLICT(cache_key)
        DO UPDATE SET file_id = excluded.file_id
    """, (key, file_id))

    await DB.commit()


async def get_mode(key, default_mode):
    async with DB.execute("""
        SELECT mode
        FROM settings
        WHERE settings_key = ?
    """, (key,)) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return default_mode

    return row[0]


async def save_mode(key, mode):
    await DB.execute("""
        INSERT INTO settings (
            settings_key,
            mode
        )
        VALUES (?, ?)
        ON CONFLICT(settings_key)
        DO UPDATE SET mode = excluded.mode
    """, (key, mode))

    await DB.commit()