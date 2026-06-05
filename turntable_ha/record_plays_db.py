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
        # busy timeout so a transient lock raises OperationalError rather than
        # hanging the control loop indefinitely.
        self._conn = sqlite3.connect(self.db_path, timeout=5)
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
        # Persistent session-id counter. Sessions where every play is shorter
        # than the recording threshold insert no record_plays rows, so deriving
        # the next id from MAX(record_plays.session_id) would reuse ids across
        # restarts and merge unrelated sessions. Tracking the counter here makes
        # each allocated session id unique for the life of the database.
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        self._cursor.execute("SELECT value FROM meta WHERE key = 'next_session_id'")
        if self._cursor.fetchone() is None:
            # Seed from any legacy data so we never collide with existing ids.
            self._cursor.execute("SELECT MAX(session_id) FROM record_plays")
            legacy_max = self._cursor.fetchone()[0] or 0
            self._cursor.execute(
                "INSERT INTO meta (key, value) VALUES ('next_session_id', ?)",
                (legacy_max + 1,),
            )
        self._conn.commit()

    def insert_record_play(self, runtime: timedelta, session_id):
        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._cursor.execute(
            "INSERT INTO record_plays (datetime, runtime, session_id) VALUES (?, ?, ?)",
            (current_datetime, runtime.total_seconds(), session_id),
        )
        self._conn.commit()

    def start_session(self) -> int:
        """Atomically allocate and persist a new, unique session id."""
        self._cursor.execute("SELECT value FROM meta WHERE key = 'next_session_id'")
        session_id = self._cursor.fetchone()[0]
        self._cursor.execute(
            "UPDATE meta SET value = ? WHERE key = 'next_session_id'",
            (session_id + 1,),
        )
        self._conn.commit()
        return session_id

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
