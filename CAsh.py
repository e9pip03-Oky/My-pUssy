import sqlite3

import Reply


DATABASE = "bot.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DATABASE,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    connection = get_connection()

    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mode_state (
                context_key TEXT PRIMARY KEY,
                mode TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reply_state (
                user_id INTEGER PRIMARY KEY,
                reply_index INTEGER NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                cache_key TEXT PRIMARY KEY,
                file_id TEXT NOT NULL
            )
            """
        )

        connection.commit()
    finally:
        connection.close()


def get_mode(context_key: str) -> str:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT mode
            FROM mode_state
            WHERE context_key = ?
            """,
            (context_key,),
        ).fetchone()

        if row is None:
            return "normal"

        return row["mode"]
    finally:
        connection.close()


def set_mode(
    context_key: str,
    mode: str,
) -> None:
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO mode_state (
                context_key,
                mode
            )
            VALUES (?, ?)
            ON CONFLICT(context_key)
            DO UPDATE SET mode = excluded.mode
            """,
            (
                context_key,
                mode,
            ),
        )

        connection.commit()
    finally:
        connection.close()


def toggle_mode(context_key: str) -> str:
    current_mode = get_mode(context_key)

    new_mode = (
        "voice"
        if current_mode == "normal"
        else "normal"
    )

    set_mode(
        context_key,
        new_mode,
    )

    return new_mode


def get_next_reply(user_id: int) -> str:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT reply_index
            FROM reply_state
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        index = (
            0
            if row is None
            else row["reply_index"]
        )

        reply = Reply.ALTERNATING_REPLIES[index]

        next_index = (
            index + 1
        ) % len(Reply.ALTERNATING_REPLIES)

        connection.execute(
            """
            INSERT INTO reply_state (
                user_id,
                reply_index
            )
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                reply_index = excluded.reply_index
            """,
            (
                user_id,
                next_index,
            ),
        )

        connection.commit()

        return reply
    finally:
        connection.close()


def get_file_id(
    cache_key: str,
) -> str | None:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT file_id
            FROM file_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

        if row is None:
            return None

        return row["file_id"]
    finally:
        connection.close()


def set_file_id(
    cache_key: str,
    file_id: str,
) -> None:
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO file_cache (
                cache_key,
                file_id
            )
            VALUES (?, ?)
            ON CONFLICT(cache_key)
            DO UPDATE SET
                file_id = excluded.file_id
            """,
            (
                cache_key,
                file_id,
            ),
        )

        connection.commit()
    finally:
        connection.close()