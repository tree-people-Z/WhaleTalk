import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from utils.database import Database
from utils.db_migrations import SCHEMA_VERSION, current_version


class DatabaseMigrationTests(unittest.TestCase):
    def test_fresh_database_is_at_current_version_with_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'fresh.db'))
            try:
                self.assertEqual(current_version(db.engine), SCHEMA_VERSION)
                with db.engine.connect() as connection:
                    journal = connection.execute(text('PRAGMA journal_mode')).scalar()
                self.assertEqual(str(journal).lower(), 'wal')
                with db.engine.connect() as connection:
                    tables = {
                        row[0] for row in connection.execute(
                            text("select name from sqlite_master where type='table'")
                        )
                    }
                self.assertIn('growth_items', tables)
                self.assertIn('observed_texts', tables)
            finally:
                db.dispose()

    def test_old_schema_gains_missing_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.db'
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    'CREATE TABLE comments (id INTEGER PRIMARY KEY, bvid TEXT)'
                )
                connection.execute(
                    'CREATE TABLE agent_sessions (id INTEGER PRIMARY KEY, summary TEXT)'
                )
                connection.execute(
                    'CREATE TABLE agent_events (id INTEGER PRIMARY KEY, event_key TEXT)'
                )
                connection.commit()
            finally:
                connection.close()

            db = Database(str(path))
            try:
                self.assertEqual(current_version(db.engine), SCHEMA_VERSION)
                with db.engine.connect() as conn:
                    comment_columns = {
                        row[1] for row in conn.execute(text('PRAGMA table_info(comments)'))
                    }
                    event_columns = {
                        row[1] for row in conn.execute(text('PRAGMA table_info(agent_events)'))
                    }
                self.assertTrue(
                    {'parent_rpid', 'parent_content', 'thread_root', 'target_user'}
                    <= comment_columns
                )
                self.assertTrue(
                    {'status', 'delivery_count', 'last_delivered_at', 'handled_at'}
                    <= event_columns
                )
            finally:
                db.dispose()


if __name__ == '__main__':
    unittest.main()
