from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class DB:
    def __init__(self, db_file: Path):
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=NORMAL')
            self.conn.execute('PRAGMA foreign_keys=ON')
            self.conn.execute('PRAGMA busy_timeout=5000')
        self.init_schema()

    def init_schema(self) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_id INTEGER,
                chat_name TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '',
                media_kind TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL DEFAULT '',
                file_ext TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER,
                grouped_id INTEGER,
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(chat_id, message_id)
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                last_message_id INTEGER NOT NULL DEFAULT 0,
                last_date TEXT NOT NULL DEFAULT '',
                total_synced INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS follows (
                chat_id INTEGER PRIMARY KEY,
                peer_id INTEGER,
                chat_name TEXT NOT NULL DEFAULT '',
                entity_ref TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                follow_enabled INTEGER NOT NULL DEFAULT 1,
                download_media INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER NOT NULL DEFAULT 0,
                last_sync_at INTEGER NOT NULL DEFAULT 0,
                last_gap_check_at INTEGER NOT NULL DEFAULT 0,
                last_event_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS mirror_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'idle',
                note TEXT NOT NULL DEFAULT '',
                last_chat_id INTEGER,
                last_message_id INTEGER,
                started_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS server_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'idle',
                note TEXT NOT NULL DEFAULT '',
                pid INTEGER,
                started_at INTEGER NOT NULL DEFAULT 0,
                last_heartbeat_at INTEGER NOT NULL DEFAULT 0,
                last_gap_check_at INTEGER NOT NULL DEFAULT 0,
                last_message_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                chat_name TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL DEFAULT '',
                save_path TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER,
                status TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(chat_id, message_id)
            )
            ''')
            cur.execute('''
            CREATE TABLE IF NOT EXISTS download_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                chat_name TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL DEFAULT '',
                file_ext TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size_expected INTEGER,
                save_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 100,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                UNIQUE(chat_id, message_id)
            )
            ''')

            # 轻量迁移：为老库补字段
            cur.execute("PRAGMA table_info(follows)")
            follow_cols = {str(row[1]) for row in cur.fetchall()}
            if 'username' not in follow_cols:
                cur.execute("ALTER TABLE follows ADD COLUMN username TEXT NOT NULL DEFAULT ''")


            cur.execute('''
            CREATE TABLE IF NOT EXISTS dialogs_cache (
                chat_id INTEGER PRIMARY KEY,
                peer_id INTEGER,
                chat_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            ''')

            cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_msg ON messages(chat_id, message_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_media ON messages(chat_id, media_kind, message_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs(status, next_retry_at, priority, id)')
            self.conn.commit()
