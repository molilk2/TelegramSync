from __future__ import annotations

import asyncio

from telethon import utils

from app.core.normalizer import normalize_message
from app.core.sync import SyncService
from app.utils import now_ts


class MirrorService:
    def __init__(self, client, repo, logger, downloader=None):
        self.client = client
        self.repo = repo
        self.logger = logger
        self.downloader = downloader
        self.syncer = SyncService(client, repo, logger, downloader)

    async def _load_targets(self, entity_like=None, *, download_media: bool = False):
        if entity_like:
            chat = await self.syncer._resolve_entity(entity_like)
            peer_id = utils.get_peer_id(chat)
            chat_id = int(getattr(chat, 'id', 0))
            chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(peer_id)
            self.repo.upsert_follow(chat_id, peer_id=peer_id, chat_name=chat_name, entity_ref=str(entity_like), follow_enabled=True, download_media=download_media)
            return [chat]

        chats = []
        for row in self.repo.list_follows(enabled_only=True):
            ref = row['entity_ref'] or row['peer_id'] or row['chat_id']
            try:
                chat = await self.syncer._resolve_entity(str(ref))
                chats.append(chat)
            except Exception as exc:
                self.repo.update_follow_progress(row['chat_id'], last_error=str(exc))
                self.logger.warning('加载 follow 目标失败 chat_id=%s ref=%s err=%s', row['chat_id'], ref, exc)
        return chats

    async def _ingest_message(self, msg, chat=None):
        if chat is None:
            try:
                chat = await msg.get_chat()
            except Exception:
                chat = None
        try:
            sender = await msg.get_sender()
        except Exception:
            sender = None
        item = normalize_message(chat, msg, sender)
        follow = self.repo.get_follow(item['chat_id'])
        dl_enabled = bool(follow['download_media']) if follow else False
        self.repo.ingest_message(item, follow_row=follow, enqueue_download=bool(dl_enabled and self.downloader and item.get('media_kind')), download_priority=10, ensure_follow=True)
        self.repo.set_mirror_state('running', '监听中', last_chat_id=item['chat_id'], last_message_id=item['message_id'], started_at=0)
        return item

    async def _gap_check_once(self, chat, *, download_media: bool):
        chat_id = int(getattr(chat, 'id', 0))
        state = self.repo.get_chat_state(chat_id)
        after_id = int((state['last_message_id'] if state else 0) or 0)
        result = await self.syncer.sync_chat(chat, resume=True, after_id=after_id, download_media=download_media, register_follow=True)
        self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error='')
        return result

    async def run(self, *, entity_like=None, download_media: bool = False, check_interval: int = 120):
        chats = await self._load_targets(entity_like, download_media=download_media)
        if not chats:
            self.logger.warning('mirror 未找到任何可监听目标')
            return {'targets': 0, 'check_interval': check_interval}

        chats_by_id = {int(getattr(chat, 'id', 0)): chat for chat in chats}
        download_map = {}
        for row in self.repo.list_follows(enabled_only=True):
            download_map[int(row['chat_id'])] = bool(row['download_media'])

        for chat_id, chat in list(chats_by_id.items()):
            try:
                await self._gap_check_once(chat, download_media=download_map.get(chat_id, download_media))
            except Exception as exc:
                self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error=str(exc))
                self.logger.exception('mirror 启动补漏失败 chat_id=%s', chat_id)

        self.repo.set_mirror_state('running', 'mirror 目标已准备，实时监听由 daemon 全局 handler 统一处理', started_at=now_ts())
        self.logger.info('mirror 已准备 %s 个目标，实时监听由 daemon 全局 handler 统一处理', len(chats_by_id))
        return {'targets': len(chats_by_id), 'check_interval': check_interval}

