"""
Simple SQLite3 Database to store record plays

Future: Log Stylus Changes and calculate stylus life
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class RecordPlaysDB:
    def __init__(self):
        db_folder = Path(os.getenv("DB_FOLDER"))
        self.db_path = db_folder / "record_plays.db"
        self.db_path.parent.mkdir(exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._cursor = self._conn.cursor()
        self._create_table()

    def _create_table(self):
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS record_plays (
                id INTEGER PRIMARY KEY,
                datetime TEXT,
                runtime INTEGER,
                session_id INTEGER
            )
        """)
        self._conn.commit()

    def insert_record_play(self, runtime: timedelta, session_id):
        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._cursor.execute(
            "INSERT INTO record_plays (datetime, runtime, session_id) VALUES (?, ?, ?)",
            (current_datetime, runtime.total_seconds(), session_id),
        )
        self._conn.commit()

    def get_next_session_id(self) -> int:
        self._cursor.execute("SELECT MAX(session_id) FROM record_plays")
        result = self._cursor.fetchone()
        return result[0] + 1 if result[0] else 1

    def get_session_runtime(self, session_id) -> int:
        self._cursor.execute(
            "SELECT SUM(runtime) FROM record_plays WHERE session_id = ?", (session_id,)
        )
        result = self._cursor.fetchone()[0]
        if result is None:
            result = 0
        return result

    def get_total_runtime(self) -> int:
        self._cursor.execute("SELECT SUM(runtime) FROM record_plays")
        result = self._cursor.fetchone()[0]
        if result is None:
            result = 0
        return result


if __name__ == "__main__":
    p = RecordPlaysDB()
    print(p.get_total_runtime())
