from __future__ import annotations

import asyncio
from pathlib import Path

from telethon.errors import FileMigrateError

try:
    from telethon.errors.rpcbaseerrors import RPCError
except Exception:  # pragma: no cover
    try:
        from telethon.errors import RPCError  # type: ignore
    except Exception:  # pragma: no cover
        RPCError = Exception  # type: ignore

from app.config.config import load_config
from app.config.paths import DOWNLOAD_DIR
from app.utils import ensure_parent, limit_path_component_lengths, sanitize_name


class DownloadManager:
    def __init__(self, repo, logger, should_stop=None):
        self.repo = repo
        self.logger = logger
        self._config_cache = None
        self.should_stop = should_stop or (lambda: False)

    def refresh_config(self) -> None:
        self._config_cache = load_config().get('mirror', {})

    def _cfg(self) -> dict:
        if self._config_cache is None:
            self.refresh_config()
        return self._config_cache or {}

    def _build_save_path(self, item: dict) -> Path:
        cfg = self._cfg()
        root = Path(cfg.get('download_root') or DOWNLOAD_DIR)
        max_component_length = int(cfg.get('max_path_component_length', 100) or 100)
        chat_name = sanitize_name(item.get('chat_name', ''), fallback=str(item.get('chat_id') or 'chat'), max_length=max_component_length)
        file_name = sanitize_name(item.get('file_name', ''), fallback='file', max_length=max_component_length)
        ext = item.get('file_ext') or ''
        filename_mode = cfg.get('filename_mode', 'message_id')

        if not file_name or file_name == 'file':
            base = f"{item.get('message_id') or 'msg'}"
            file_name = f'{base}{ext}' if ext and not str(base).endswith(ext) else base
        elif ext and not file_name.endswith(ext):
            file_name = sanitize_name(f'{file_name}{ext}', fallback='file', max_length=max_component_length)

        if filename_mode == 'message_id':
            suffix = Path(file_name).suffix
            file_name = sanitize_name(f"{item.get('message_id') or 'msg'}{suffix}", fallback='file', max_length=max_component_length)

        if cfg.get('organize_by_chat', True):
            return limit_path_component_lengths(root / chat_name / file_name, max_component_length=max_component_length)
        return limit_path_component_lengths(root / file_name, max_component_length=max_component_length)

    def _is_retryable_download_error(self, exc: Exception) -> bool:
        if isinstance(exc, (FileMigrateError, asyncio.IncompleteReadError, TimeoutError, ConnectionError, OSError)):
            return True
        text = str(exc).lower()
        markers = (
            'server closed the connection',
            '0 bytes read',
            'incompletereaderror',
            'connection was closed',
            'connection reset',
            'timed out',
            'timeout',
            'broken pipe',
        )
        return any(m in text for m in markers)

    async def _reconnect_client(self, client) -> None:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        await asyncio.sleep(1)
        if not client.is_connected():
            await client.connect()

    async def _download_with_retry(self, client, msg, save_path: Path) -> None:
        cfg = self._cfg()
        max_attempts = int(cfg.get('download_max_attempts_per_round', 4) or 4)
        backoff_base = int(cfg.get('download_retry_backoff_base', 2) or 2)
        backoff_cap = int(cfg.get('download_retry_backoff_cap', 20) or 20)
        overwrite = bool(cfg.get('overwrite', False))
        temp_path = save_path.with_name(save_path.name + '.part')

        if save_path.exists() and not overwrite:
            return

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if self.should_stop():
                raise RuntimeError('server stopping')
            try:
                ensure_parent(temp_path)
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                if not client.is_connected():
                    await client.connect()
                await client.download_media(msg, file=str(temp_path))
                if save_path.exists() and overwrite:
                    save_path.unlink(missing_ok=True)
                temp_path.replace(save_path)
                return
            except Exception as exc:
                last_exc = exc
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                if attempt >= max_attempts or not self._is_retryable_download_error(exc):
                    raise
                self.logger.warning(
                    '下载重试 chat=%s msg=%s attempt=%s/%s err=%s',
                    getattr(msg, 'chat_id', None),
                    getattr(msg, 'id', None),
                    attempt,
                    max_attempts,
                    exc,
                )
                await self._reconnect_client(client)
                if self.should_stop():
                    raise RuntimeError('server stopping')
                await asyncio.sleep(min(backoff_base ** (attempt - 1), backoff_cap))

        if last_exc is not None:
            raise last_exc

    async def enqueue_from_item(self, item: dict, *, priority: int = 100) -> None:
        if not item.get('media_kind'):
            return
        await self.repo.enqueue_download(item, priority=priority)

    async def _resolve_job_input_entity(self, client, job: dict):
        follow = await self.repo.get_follow(int(job.get('chat_id') or 0))
        candidates = []
        if follow is not None:
            peer_id = follow['peer_id'] if 'peer_id' in follow.keys() else None
            username = str((follow['username'] if 'username' in follow.keys() else '') or '').strip()
            entity_ref = str((follow['entity_ref'] if 'entity_ref' in follow.keys() else '') or '').strip()
            if peer_id not in (None, '', 0, '0'):
                candidates.append(peer_id)
            if username:
                candidates.append(username)
            if entity_ref and not entity_ref.startswith('Channel(') and not entity_ref.startswith('Chat(') and not entity_ref.startswith('User('):
                candidates.append(entity_ref)
        candidates.append(job.get('chat_id'))

        last_exc = None
        for ref in candidates:
            if ref in (None, '', 0, '0'):
                continue
            try:
                return await client.get_input_entity(ref)
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return job.get('chat_id')

    async def process_one_job(self, client) -> bool:
        job = await self.repo.reserve_download_job()
        if not job:
            return False

        item = dict(job)
        save_path = self._build_save_path(item)
        ensure_parent(save_path)
        try:
            if not client.is_connected():
                await client.connect()
            entity = await self._resolve_job_input_entity(client, item)
            msg = await client.get_messages(entity, ids=job['message_id'])
            if not msg or not getattr(msg, 'media', None):
                await self.repo.finish_download_job(job['id'], 'skipped', save_path=str(save_path), error='消息不存在或无媒体')
                await self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'skipped', 'note': '消息不存在或无媒体'})
                return True

            await self._download_with_retry(client, msg, save_path)
            await self.repo.finish_download_job(job['id'], 'done', save_path=str(save_path))
            await self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'done', 'note': ''})
            self.logger.info('下载完成 chat=%s msg=%s path=%s', item.get('chat_id'), item.get('message_id'), save_path)
            return True
        except (RPCError, Exception) as exc:
            cfg = self._cfg()
            retry_delay = int(cfg.get('download_job_retry_delay', 180) or 180)
            await self.repo.finish_download_job(job['id'], 'failed', save_path=str(save_path), error=str(exc), retry_delay=retry_delay)
            await self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'error', 'note': str(exc)})
            self.logger.exception('下载失败 chat=%s msg=%s', item.get('chat_id'), item.get('message_id'))
            return True

    async def worker_loop(self, client, *, poll_interval: int = 3):
        while True:
            handled = await self.process_one_job(client)
            if not handled:
                await asyncio.sleep(poll_interval)
