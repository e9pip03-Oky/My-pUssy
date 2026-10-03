import os
import sqlite3
import json

DB_PATH = os.path.join(os.getcwd(), "bot_database.db")

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    mode TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_cache (
                    url TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    file_data TEXT NOT NULL,
                    PRIMARY KEY (url, mode)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_reply_index (
                    user_id INTEGER PRIMARY KEY,
                    idx INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()

    def get_mode(self, key: str) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mode FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else "normal"

    def set_mode(self, key: str, mode: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, mode) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET mode = excluded.mode
            """, (key, mode))
            conn.commit()

    def get_cached_map(self, url: str, mode: str) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_data FROM file_cache WHERE url = ? AND mode = ?", (url, mode))
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except Exception:
                    return {}
            return {}

    def update_cached_map(self, url: str, mode: str, new_entries: dict):
        current_map = self.get_cached_map(url, mode)
        current_map.update(new_entries)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO file_cache (url, mode, file_data) VALUES (?, ?, ?)
                ON CONFLICT(url, mode) DO UPDATE SET file_data = excluded.file_data
            """, (url, mode, json.dumps(current_map)))
            conn.commit()

    def get_next_reply_index(self, user_id: int, total_replies: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT idx FROM user_reply_index WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                current_idx = row[0]
                next_idx = (current_idx + 1) % total_replies
                cursor.execute("UPDATE user_reply_index SET idx = ? WHERE user_id = ?", (next_idx, user_id))
            else:
                current_idx = 0
                next_idx = 1 % total_replies
                cursor.execute("INSERT INTO user_reply_index (user_id, idx) VALUES (?, ?)", (user_id, next_idx))
            conn.commit()
            return current_idx

db = Database()
