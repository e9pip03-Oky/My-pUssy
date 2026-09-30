import sqlite3
import threading
from pathlib import Path


class Database:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            path,
            check_same_thread=False,
        )
        self.lock = threading.RLock()
        self._create_tables()

    def _create_tables(self):
        with self.lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS modes (
                    scope TEXT PRIMARY KEY,
                    mode TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS replies (
                    user_id INTEGER PRIMARY KEY,
                    position INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS developer_rotation (
                    dimension TEXT PRIMARY KEY,
                    position INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS normal_file_ids (
                    cache_key TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    file_name TEXT
                );

                CREATE TABLE IF NOT EXISTS voice_file_ids (
                    cache_key TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    file_name TEXT
                );
                """
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO developer_rotation(dimension) VALUES (?)",
                (("id",), ("name",), ("style",)),
            )

    def get_mode(self, scope, default):
        with self.lock:
            row = self.connection.execute(
                "SELECT mode FROM modes WHERE scope = ?",
                (scope,),
            ).fetchone()
        return row[0] if row else default

    def set_mode(self, scope, mode):
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO modes(scope, mode) VALUES (?, ?)
                ON CONFLICT(scope) DO UPDATE SET mode = excluded.mode
                """,
                (scope, mode),
            )

    def next_reply(self, user_id, total):
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT position FROM replies WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            position = row[0] if row else 0
            self.connection.execute(
                """
                INSERT INTO replies(user_id, position) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET position = excluded.position
                """,
                (user_id, (position + 1) % total),
            )
        return position

    def next_developer(self, totals):
        values = {}
        with self.lock, self.connection:
            for dimension, total in totals.items():
                row = self.connection.execute(
                    "SELECT position FROM developer_rotation WHERE dimension = ?",
                    (dimension,),
                ).fetchone()
                position = row[0] if row else 0
                values[dimension] = position % total
                self.connection.execute(
                    "UPDATE developer_rotation SET position = ? WHERE dimension = ?",
                    ((position + 1) % total, dimension),
                )
        return values

    def get_file_id(self, mode, cache_key):
        table = "normal_file_ids" if mode == "normal" else "voice_file_ids"
        with self.lock:
            row = self.connection.execute(
                f"SELECT file_id FROM {table} WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return row[0] if row else None

    def save_file_id(self, mode, cache_key, file_id, file_name):
        table = "normal_file_ids" if mode == "normal" else "voice_file_ids"
        with self.lock, self.connection:
            self.connection.execute(
                f"""
                INSERT INTO {table}(cache_key, file_id, file_name)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    file_id = excluded.file_id,
                    file_name = excluded.file_name
                """,
                (cache_key, file_id, file_name),
            )

    def close(self):
        with self.lock:
            self.connection.close()
