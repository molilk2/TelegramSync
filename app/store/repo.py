from __future__ import annotations

import os

from app.utils import dump_json_compact_compressed, now_ts


class Repo:
    def __init__(self, db):
        self.db = db
        self.conn = db.conn
        self.lock = db.lock

    def save_message(self, data: dict, *, commit: bool = True) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO messages (
                chat_id, message_id, sender_id, chat_name, sender_name, date, text, raw_json,
                media_kind, file_name, file_ext, mime_type, file_size, grouped_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                sender_id=excluded.sender_id,
                chat_name=excluded.chat_name,
                sender_name=excluded.sender_name,
                date=excluded.date,
                text=excluded.text,
                raw_json=CASE WHEN excluded.raw_json <> '' THEN excluded.raw_json ELSE messages.raw_json END,
                media_kind=excluded.media_kind,
                file_name=excluded.file_name,
                file_ext=excluded.file_ext,
                mime_type=excluded.mime_type,
                file_size=excluded.file_size,
                grouped_id=excluded.grouped_id,
                updated_at=excluded.updated_at
            ''',
                (
                    data.get('chat_id'), data.get('message_id'), data.get('sender_id'), data.get('chat_name', ''),
                    data.get('sender_name', ''), data.get('date', ''), data.get('text', ''),
                    dump_json_compact_compressed(data.get('raw', {})), data.get('media_kind', ''),
                    data.get('file_name', ''), data.get('file_ext', ''), data.get('mime_type', ''),
                    data.get('file_size'), data.get('grouped_id'), ts, ts,
                ),
            )
            if commit:
                self.conn.commit()

    def update_chat_state(self, chat_id: int, message_id: int, date: str, *, commit: bool = True) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO chat_state (chat_id, last_message_id, last_date, total_synced, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                last_message_id = CASE WHEN excluded.last_message_id > chat_state.last_message_id THEN excluded.last_message_id ELSE chat_state.last_message_id END,
                last_date = CASE WHEN excluded.last_message_id >= chat_state.last_message_id THEN excluded.last_date ELSE chat_state.last_date END,
                total_synced = CASE WHEN excluded.last_message_id > chat_state.last_message_id THEN chat_state.total_synced + 1 ELSE chat_state.total_synced END,
                updated_at = excluded.updated_at
            ''',
                (chat_id, message_id, date or '', ts),
            )
            if commit:
                self.conn.commit()

    def get_chat_state(self, chat_id: int):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM chat_state WHERE chat_id=?', (chat_id,))
            return cur.fetchone()

    def list_chat_states(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM chat_state ORDER BY updated_at DESC, chat_id DESC')
            return cur.fetchall()

    def create_run(self, run_type: str, target: str, note: str = '') -> int:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                'INSERT INTO runs (run_type, target, status, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                (run_type, target, 'running', note, ts, ts),
            )
            self.conn.commit()
            return cur.lastrowid

    def finish_run(self, run_id: int, status: str, note: str = '') -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('UPDATE runs SET status=?, note=?, updated_at=? WHERE id=?', (status, note, now_ts(), run_id))
            self.conn.commit()

    def recent_runs(self, limit: int = 20):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM runs ORDER BY id DESC LIMIT ?', (limit,))
            return cur.fetchall()

    def set_mirror_state(self, status: str, note: str = '', last_chat_id=None, last_message_id=None, started_at: int | None = None) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO mirror_state (id, status, note, last_chat_id, last_message_id, started_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                note=excluded.note,
                last_chat_id=COALESCE(excluded.last_chat_id, mirror_state.last_chat_id),
                last_message_id=COALESCE(excluded.last_message_id, mirror_state.last_message_id),
                started_at=CASE WHEN excluded.started_at > 0 THEN excluded.started_at ELSE mirror_state.started_at END,
                updated_at=excluded.updated_at
            ''',
                (status, note, last_chat_id, last_message_id, started_at or 0, ts),
            )
            self.conn.commit()

    def get_mirror_state(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM mirror_state WHERE id=1')
            return cur.fetchone()

    def set_server_state(self, status: str, note: str = '', *, pid: int | None = None, started_at: int | None = None,
                         last_heartbeat_at: int | None = None, last_gap_check_at: int | None = None,
                         last_message_at: int | None = None, last_error: str | None = None) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO server_state (id, status, note, pid, started_at, last_heartbeat_at, last_gap_check_at, last_message_at, last_error, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                note=excluded.note,
                pid=COALESCE(excluded.pid, server_state.pid),
                started_at=CASE WHEN excluded.started_at > 0 THEN excluded.started_at ELSE server_state.started_at END,
                last_heartbeat_at=CASE WHEN excluded.last_heartbeat_at > 0 THEN excluded.last_heartbeat_at ELSE server_state.last_heartbeat_at END,
                last_gap_check_at=CASE WHEN excluded.last_gap_check_at > 0 THEN excluded.last_gap_check_at ELSE server_state.last_gap_check_at END,
                last_message_at=CASE WHEN excluded.last_message_at > 0 THEN excluded.last_message_at ELSE server_state.last_message_at END,
                last_error=CASE WHEN excluded.last_error IS NOT NULL THEN excluded.last_error ELSE server_state.last_error END,
                updated_at=excluded.updated_at
            ''',
                (
                    status,
                    note,
                    pid,
                    started_at or 0,
                    last_heartbeat_at or 0,
                    last_gap_check_at or 0,
                    last_message_at or 0,
                    last_error if last_error is not None else '',
                    ts,
                ),
            )
            self.conn.commit()

    def get_server_state(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM server_state WHERE id=1')
            return cur.fetchone()

    def save_download(self, data: dict) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO downloads (
                chat_id, message_id, chat_name, sender_name, file_name, save_path,
                mime_type, file_size, status, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                file_name=excluded.file_name,
                save_path=excluded.save_path,
                mime_type=excluded.mime_type,
                file_size=excluded.file_size,
                status=excluded.status,
                note=excluded.note,
                updated_at=excluded.updated_at
            ''',
                (
                    data.get('chat_id'), data.get('message_id'), data.get('chat_name', ''), data.get('sender_name', ''),
                    data.get('file_name', ''), data.get('save_path', ''), data.get('mime_type', ''), data.get('file_size'),
                    data.get('status', ''), data.get('note', ''), ts, ts,
                ),
            )
            self.conn.commit()

    def upsert_follow(self, chat_id: int, peer_id: int | None, chat_name: str = '', entity_ref: str = '', username: str = '',
                      follow_enabled: bool = True, download_media: bool = False, last_message_id: int = 0,
                      last_sync_at: int | None = None, last_gap_check_at: int | None = None,
                      last_event_at: int | None = None, last_error: str | None = None, commit: bool = True) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO follows (
                chat_id, peer_id, chat_name, entity_ref, username, follow_enabled, download_media,
                last_message_id, last_sync_at, last_gap_check_at, last_event_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                peer_id=COALESCE(excluded.peer_id, follows.peer_id),
                chat_name=CASE WHEN excluded.chat_name <> '' THEN excluded.chat_name ELSE follows.chat_name END,
                entity_ref=CASE WHEN excluded.entity_ref <> '' THEN excluded.entity_ref ELSE follows.entity_ref END,
                username=CASE WHEN excluded.username <> '' THEN excluded.username ELSE follows.username END,
                follow_enabled=excluded.follow_enabled,
                download_media=excluded.download_media,
                last_message_id=CASE WHEN excluded.last_message_id > follows.last_message_id THEN excluded.last_message_id ELSE follows.last_message_id END,
                last_sync_at=CASE WHEN excluded.last_sync_at > 0 THEN excluded.last_sync_at ELSE follows.last_sync_at END,
                last_gap_check_at=CASE WHEN excluded.last_gap_check_at > 0 THEN excluded.last_gap_check_at ELSE follows.last_gap_check_at END,
                last_event_at=CASE WHEN excluded.last_event_at > 0 THEN excluded.last_event_at ELSE follows.last_event_at END,
                last_error=CASE WHEN excluded.last_error IS NOT NULL THEN excluded.last_error ELSE follows.last_error END,
                updated_at=excluded.updated_at
            ''',
                (chat_id, peer_id, chat_name, entity_ref, username, 1 if follow_enabled else 0, 1 if download_media else 0,
                 last_message_id, last_sync_at or 0, last_gap_check_at or 0, last_event_at or 0, last_error or '', ts, ts),
            )
            if commit:
                self.conn.commit()

    def update_follow_progress(self, chat_id: int, *, last_message_id: int | None = None, last_sync_at: int | None = None,
                               last_gap_check_at: int | None = None, last_event_at: int | None = None,
                               last_error: str | None = None, chat_name: str | None = None, peer_id: int | None = None):
        row = self.get_follow(chat_id)
        if not row:
            self.upsert_follow(chat_id, peer_id=peer_id, chat_name=chat_name or '', follow_enabled=True)
            row = self.get_follow(chat_id)
        self.upsert_follow(
            chat_id,
            peer_id=peer_id if peer_id is not None else row['peer_id'],
            chat_name=chat_name if chat_name is not None else row['chat_name'],
            entity_ref=row['entity_ref'],
            username=row['username'],
            follow_enabled=bool(row['follow_enabled']),
            download_media=bool(row['download_media']),
            last_message_id=last_message_id if last_message_id is not None else row['last_message_id'],
            last_sync_at=last_sync_at if last_sync_at is not None else row['last_sync_at'],
            last_gap_check_at=last_gap_check_at if last_gap_check_at is not None else row['last_gap_check_at'],
            last_event_at=last_event_at if last_event_at is not None else row['last_event_at'],
            last_error=last_error if last_error is not None else row['last_error'],
        )

    def get_follow(self, chat_id: int):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM follows WHERE chat_id=?', (chat_id,))
            return cur.fetchone()

    def list_follows(self, enabled_only: bool = False):
        with self.lock:
            cur = self.conn.cursor()
            if enabled_only:
                cur.execute('SELECT * FROM follows WHERE follow_enabled=1 ORDER BY updated_at DESC, chat_id DESC')
            else:
                cur.execute('SELECT * FROM follows ORDER BY updated_at DESC, chat_id DESC')
            return cur.fetchall()

    def set_follow_enabled(self, chat_id: int, enabled: bool) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('UPDATE follows SET follow_enabled=?, updated_at=? WHERE chat_id=?', (1 if enabled else 0, now_ts(), chat_id))
            self.conn.commit()

    def remove_follow(self, chat_id: int) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('DELETE FROM follows WHERE chat_id=?', (chat_id,))
            self.conn.commit()

    def set_follow_download_media(self, chat_id: int, enabled: bool) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('UPDATE follows SET download_media=?, updated_at=? WHERE chat_id=?', (1 if enabled else 0, now_ts(), chat_id))
            self.conn.commit()

    def enqueue_download(self, item: dict, *, priority: int = 100, next_retry_at: int | None = None, commit: bool = True) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
            INSERT INTO download_jobs (
                chat_id, message_id, chat_name, sender_name, file_name, file_ext, mime_type, file_size_expected,
                save_path, status, priority, retry_count, next_retry_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, '', ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                chat_name=excluded.chat_name,
                sender_name=excluded.sender_name,
                file_name=excluded.file_name,
                file_ext=excluded.file_ext,
                mime_type=excluded.mime_type,
                file_size_expected=excluded.file_size_expected,
                priority=MIN(download_jobs.priority, excluded.priority),
                next_retry_at=CASE WHEN download_jobs.status IN ('done','downloading') THEN download_jobs.next_retry_at ELSE excluded.next_retry_at END,
                updated_at=excluded.updated_at
            ''',
                (item.get('chat_id'), item.get('message_id'), item.get('chat_name', ''), item.get('sender_name', ''),
                 item.get('file_name', ''), item.get('file_ext', ''), item.get('mime_type', ''), item.get('file_size'), '',
                 priority, next_retry_at or 0, ts, ts),
            )
            if commit:
                self.conn.commit()

    def reserve_download_job(self):
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
                SELECT * FROM download_jobs
                WHERE status IN ('pending','failed') AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY priority ASC, id ASC LIMIT 1
                ''',
                (ts,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute('UPDATE download_jobs SET status=?, updated_at=? WHERE id=?', ('downloading', ts, row['id']))
            self.conn.commit()
            cur.execute('SELECT * FROM download_jobs WHERE id=?', (row['id'],))
            return cur.fetchone()

    def reclaim_stale_download_jobs(self, stale_after_seconds: int = 600) -> int:
        ts = now_ts()
        cutoff = ts - int(stale_after_seconds or 600)
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
                UPDATE download_jobs
                SET status='pending',
                    next_retry_at=?,
                    last_error=CASE WHEN last_error <> '' THEN last_error || ' | stale lease reclaimed' ELSE 'stale lease reclaimed' END,
                    updated_at=?
                WHERE status='downloading' AND updated_at > 0 AND updated_at < ?
                ''',
                (ts, ts, cutoff),
            )
            changed = cur.rowcount or 0
            self.conn.commit()
            return changed

    def finish_download_job(self, job_id: int, status: str, *, save_path: str = '', file_size_actual: int | None = None, error: str = '', retry_delay: int = 60):
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            if status == 'failed':
                cur.execute('SELECT retry_count FROM download_jobs WHERE id=?', (job_id,))
                row = cur.fetchone()
                retry_count = int((row['retry_count'] if row else 0) or 0) + 1
                next_retry_at = ts + retry_delay
                cur.execute(
                    'UPDATE download_jobs SET status=?, retry_count=?, next_retry_at=?, save_path=?, last_error=?, updated_at=? WHERE id=?',
                    ('failed', retry_count, next_retry_at, save_path, error, ts, job_id),
                )
            else:
                cur.execute(
                    'UPDATE download_jobs SET status=?, save_path=?, last_error=?, updated_at=? WHERE id=?',
                    (status, save_path, error, ts, job_id),
                )
            self.conn.commit()

    def get_message_by_key(self, chat_id: int, message_id: int):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM messages WHERE chat_id=? AND message_id=?', (chat_id, message_id))
            return cur.fetchone()

    def list_messages_with_media_missing_download(self, chat_id: int | None = None, limit: int = 1000):
        q = '''
            SELECT m.* FROM messages m
            LEFT JOIN download_jobs j ON j.chat_id=m.chat_id AND j.message_id=m.message_id
            WHERE m.media_kind <> '' AND (j.id IS NULL OR j.status NOT IN ('pending','downloading','done'))
        '''
        params: list = []
        if chat_id is not None:
            q += ' AND m.chat_id=?'
            params.append(chat_id)
        q += ' ORDER BY m.chat_id ASC, m.message_id ASC LIMIT ?'
        params.append(limit)
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(q, params)
            return cur.fetchall()

    def ingest_message(self, item: dict, *, follow_row=None, enqueue_download: bool = False, download_priority: int = 10, ensure_follow: bool = False):
        ts = now_ts()
        with self.lock:
            self.save_message(item, commit=False)
            self.update_chat_state(int(item.get('chat_id') or 0), int(item.get('message_id') or 0), item.get('date', ''), commit=False)

            row = follow_row
            chat_id = int(item.get('chat_id') or 0)
            if row is None and (ensure_follow or enqueue_download):
                cur = self.conn.cursor()
                cur.execute('SELECT * FROM follows WHERE chat_id=?', (chat_id,))
                row = cur.fetchone()

            if row is not None:
                self.upsert_follow(
                    chat_id,
                    peer_id=row['peer_id'] if 'peer_id' in row.keys() else None,
                    chat_name=item.get('chat_name') or row['chat_name'],
                    entity_ref=row['entity_ref'] if 'entity_ref' in row.keys() else '',
                    username=row['username'] if 'username' in row.keys() else '',
                    follow_enabled=bool(row['follow_enabled']) if 'follow_enabled' in row.keys() else True,
                    download_media=bool(row['download_media']) if 'download_media' in row.keys() else False,
                    last_message_id=int(item.get('message_id') or 0),
                    last_sync_at=row['last_sync_at'] if 'last_sync_at' in row.keys() else 0,
                    last_gap_check_at=row['last_gap_check_at'] if 'last_gap_check_at' in row.keys() else 0,
                    last_event_at=ts,
                    last_error='',
                    commit=False,
                )
            elif ensure_follow:
                self.upsert_follow(
                    chat_id,
                    peer_id=None,
                    chat_name=item.get('chat_name', ''),
                    follow_enabled=True,
                    download_media=False,
                    last_message_id=int(item.get('message_id') or 0),
                    last_event_at=ts,
                    last_error='',
                    commit=False,
                )

            if enqueue_download and item.get('media_kind'):
                self.enqueue_download(item, priority=download_priority, commit=False)

            self.conn.commit()

    def get_download_job_stats(self):
        with self.lock:
            cur = self.conn.cursor()
            out = {}
            for status in ('pending', 'downloading', 'done', 'failed', 'skipped'):
                cur.execute('SELECT COUNT(*) AS c FROM download_jobs WHERE status=?', (status,))
                out[status] = cur.fetchone()['c']
            return out

    def recent_download_jobs(self, limit: int = 20):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM download_jobs ORDER BY id DESC LIMIT ?', (limit,))
            return cur.fetchall()

    def stats(self) -> dict:
        with self.lock:
            cur = self.conn.cursor()
            out = {}
            for table in ('messages', 'chat_state', 'follows', 'runs', 'downloads', 'download_jobs'):
                cur.execute(f'SELECT COUNT(*) AS c FROM {table}')
                out[table] = cur.fetchone()['c']
            cur.execute('SELECT COUNT(*) AS c FROM messages WHERE media_kind <> ""')
            out['messages_with_media'] = cur.fetchone()['c']
            cur.execute('SELECT COUNT(DISTINCT chat_id) AS c FROM messages')
            out['chats_with_messages'] = cur.fetchone()['c']
            cur.execute('SELECT COUNT(*) AS c FROM follows WHERE follow_enabled=1')
            out['follows_enabled'] = cur.fetchone()['c']
            cur.execute('SELECT COUNT(*) AS c FROM follows WHERE download_media=1')
            out['follows_download_enabled'] = cur.fetchone()['c']
            out.update({f'download_jobs_{k}': v for k, v in self.get_download_job_stats().items()})
            return out

    def db_file_stats(self) -> dict:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('PRAGMA database_list')
            row = cur.fetchone()
            db_path = row['file'] if row else ''
        out = {'db_path': db_path, 'db_size': 0, 'wal_size': 0, 'shm_size': 0}
        if db_path:
            for key, suffix in [('db_size', ''), ('wal_size', '-wal'), ('shm_size', '-shm')]:
                path = db_path + suffix
                if os.path.exists(path):
                    out[key] = os.path.getsize(path)
        return out

    def save_dialog_cache(self, *, chat_id: int, peer_id: int | None, chat_name: str = '', username: str = '', entity_type: str = '') -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                '''
                INSERT INTO dialogs_cache (chat_id, peer_id, chat_name, username, entity_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    peer_id=excluded.peer_id,
                    chat_name=excluded.chat_name,
                    username=excluded.username,
                    entity_type=excluded.entity_type,
                    updated_at=excluded.updated_at
                ''',
                (chat_id, peer_id, chat_name, username, entity_type, ts),
            )
            self.conn.commit()

    def list_dialog_cache(self, limit: int = 200):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('SELECT * FROM dialogs_cache ORDER BY updated_at DESC, chat_name ASC LIMIT ?', (limit,))
            return cur.fetchall()

    def replace_dialog_cache(self, rows: list[dict]) -> None:
        ts = now_ts()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('DELETE FROM dialogs_cache')
            for row in rows:
                cur.execute(
                    '''
                    INSERT INTO dialogs_cache (chat_id, peer_id, chat_name, username, entity_type, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (row.get('chat_id'), row.get('peer_id'), row.get('chat_name', ''), row.get('username', ''), row.get('entity_type', ''), row.get('updated_at', ts)),
                )
            self.conn.commit()

    def clear_dialog_cache(self) -> None:
        with self.lock:
            self.conn.execute('DELETE FROM dialogs_cache')
            self.conn.commit()

    def optimize_database(self) -> dict:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            _ = cur.fetchall() if cur.description else []
            cur.execute('VACUUM')
            self.conn.commit()
        return self.db_file_stats()
