from __future__ import annotations

import asyncio
from pathlib import Path

from app.config.config import load_config
from app.config.paths import DOWNLOAD_DIR
from app.utils import ensure_parent, sanitize_name


class DownloadManager:
    def __init__(self, repo, logger):
        self.repo = repo
        self.logger = logger

    def _build_save_path(self, item: dict) -> Path:
        cfg = load_config().get('mirror', {})
        root = Path(cfg.get('download_root') or DOWNLOAD_DIR)
        chat_name = sanitize_name(item.get('chat_name', ''), fallback=str(item.get('chat_id') or 'chat'))
        file_name = sanitize_name(item.get('file_name', ''), fallback='file')
        ext = item.get('file_ext') or ''
        filename_mode = cfg.get('filename_mode', 'message_id')

        if not file_name or file_name == 'file':
            base = f"{item.get('message_id') or 'msg'}"
            file_name = f'{base}{ext}' if ext and not str(base).endswith(ext) else base
        elif ext and not file_name.endswith(ext):
            file_name = f'{file_name}{ext}'

        if filename_mode == 'message_id':
            suffix = Path(file_name).suffix
            file_name = f"{item.get('message_id') or 'msg'}{suffix}"

        if cfg.get('organize_by_chat', True):
            return root / chat_name / file_name
        return root / file_name

    def enqueue_from_item(self, item: dict, *, priority: int = 100) -> None:
        if not item.get('media_kind'):
            return
        self.repo.enqueue_download(item, priority=priority)

    async def process_one_job(self, client) -> bool:
        job = self.repo.reserve_download_job()
        if not job:
            return False

        item = dict(job)
        save_path = self._build_save_path(item)
        ensure_parent(save_path)
        try:
            msg = await client.get_messages(job['chat_id'], ids=job['message_id'])
            if not msg or not getattr(msg, 'media', None):
                self.repo.finish_download_job(job['id'], 'skipped', save_path=str(save_path), error='消息不存在或无媒体')
                self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'skipped', 'note': '消息不存在或无媒体'})
                return True

            await client.download_media(msg, file=str(save_path))
            self.repo.finish_download_job(job['id'], 'done', save_path=str(save_path))
            self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'done', 'note': ''})
            self.logger.info('下载完成 chat=%s msg=%s path=%s', item.get('chat_id'), item.get('message_id'), save_path)
            return True
        except Exception as exc:
            self.repo.finish_download_job(job['id'], 'failed', save_path=str(save_path), error=str(exc), retry_delay=60)
            self.repo.save_download({**item, 'save_path': str(save_path), 'status': 'error', 'note': str(exc)})
            self.logger.exception('下载失败 chat=%s msg=%s', item.get('chat_id'), item.get('message_id'))
            return True

    async def worker_loop(self, client, *, poll_interval: int = 3):
        while True:
            handled = await self.process_one_job(client)
            if not handled:
                await asyncio.sleep(poll_interval)
