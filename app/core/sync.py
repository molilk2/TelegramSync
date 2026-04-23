from __future__ import annotations

import asyncio
import contextlib

from telethon import events, utils
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

from app.core.normalizer import normalize_message
from app.utils import now_ts


class SyncService:
    def __init__(self, client, repo, logger, downloader=None):
        self.client = client
        self.repo = repo
        self.logger = logger
        self.downloader = downloader

    async def list_dialogs(self, limit: int = 100):
        dialogs = []
        async for dialog in self.client.iter_dialogs(limit=limit):
            entity = dialog.entity
            internal_id = getattr(entity, 'id', None)
            try:
                peer_id = utils.get_peer_id(entity)
            except Exception:
                peer_id = internal_id
            dialogs.append({'id': internal_id, 'peer_id': peer_id, 'name': dialog.name, 'username': getattr(entity, 'username', None), 'is_user': dialog.is_user, 'is_group': dialog.is_group, 'is_channel': dialog.is_channel})
        return dialogs

    async def _resolve_entity(self, entity_like):
        value = entity_like
        if isinstance(value, str):
            value = value.strip()
            if value:
                try:
                    raw_id = int(value)
                    if str(raw_id).startswith('-100'):
                        return await self.client.get_entity(PeerChannel(int(str(raw_id)[4:])))
                    if raw_id < 0:
                        return await self.client.get_entity(PeerChat(abs(raw_id)))
                    return await self.client.get_entity(PeerUser(raw_id))
                except ValueError:
                    pass
        return await self.client.get_entity(value)

    async def sync_chat(self, entity_like, *, limit: int = 0, resume: bool = True, oldest_first: bool = True,
                        after_id: int = 0, download_media: bool = False, register_follow: bool = True) -> dict:
        chat = await self._resolve_entity(entity_like)
        chat_id = int(getattr(chat, 'id', 0))
        peer_id = utils.get_peer_id(chat)
        chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(peer_id)

        offset_id = int(after_id or 0)
        if resume and offset_id <= 0:
            state = self.repo.get_chat_state(chat_id)
            if state:
                offset_id = int(state['last_message_id'] or 0)

        total = 0
        self.logger.info('开始同步 chat=%s internal_id=%s peer_id=%s resume=%s offset_id=%s limit=%s oldest_first=%s', chat_name, chat_id, peer_id, resume, offset_id, limit, oldest_first)

        async for msg in self.client.iter_messages(chat, limit=None if limit == 0 else limit, reverse=oldest_first, min_id=offset_id):
            sender = None
            try:
                sender = await msg.get_sender()
            except Exception:
                sender = None
            item = normalize_message(chat, msg, sender)
            self.repo.save_message(item)
            self.repo.update_chat_state(item['chat_id'], item['message_id'], item.get('date', ''))
            if download_media and self.downloader and item.get('media_kind'):
                self.downloader.enqueue_from_item(item, priority=50)
            total += 1
            if total % 100 == 0:
                self.logger.info('同步中 chat=%s internal_id=%s peer_id=%s 已处理 %s 条', chat_name, chat_id, peer_id, total)

        if register_follow:
            state = self.repo.get_chat_state(chat_id)
            self.repo.upsert_follow(
                chat_id=chat_id,
                peer_id=peer_id,
                chat_name=chat_name,
                entity_ref=str(entity_like),
                follow_enabled=True,
                download_media=download_media,
                last_message_id=int((state['last_message_id'] if state else 0) or 0),
                last_sync_at=now_ts(),
                last_gap_check_at=now_ts(),
                last_event_at=0,
            )

        self.logger.info('同步完成 chat=%s internal_id=%s peer_id=%s total=%s', chat_name, chat_id, peer_id, total)
        return {'chat_id': chat_id, 'peer_id': peer_id, 'chat_name': chat_name, 'total': total, 'resume_from': offset_id}

    async def backfill_media(self, chat_id: int | None = None, *, limit: int = 1000) -> int:
        rows = self.repo.list_messages_with_media_missing_download(chat_id=chat_id, limit=limit)
        count = 0
        for row in rows:
            self.downloader.enqueue_from_item(dict(row), priority=20)
            count += 1
        return count

    async def follow_chat(self, entity_like, *, download_media: bool = False, check_interval: int = 120):
        chat = await self._resolve_entity(entity_like)
        chat_id = int(getattr(chat, 'id', 0))
        peer_id = utils.get_peer_id(chat)
        chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(peer_id)
        self.repo.upsert_follow(chat_id=chat_id, peer_id=peer_id, chat_name=chat_name, entity_ref=str(entity_like), follow_enabled=True, download_media=download_media)

        async def gap_loop():
            while True:
                try:
                    state = self.repo.get_chat_state(chat_id)
                    after_id = int((state['last_message_id'] if state else 0) or 0)
                    await self.sync_chat(chat, resume=True, after_id=after_id, download_media=download_media)
                    self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error='')
                except Exception as exc:
                    self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error=str(exc))
                    self.logger.exception('持续补漏失败 chat_id=%s', chat_id)
                await asyncio.sleep(check_interval)

        @self.client.on(events.NewMessage(chats=chat))
        async def on_new_message(event):
            sender = None
            try:
                sender = await event.message.get_sender()
            except Exception:
                sender = None
            item = normalize_message(chat, event.message, sender)
            self.repo.save_message(item)
            self.repo.update_chat_state(item['chat_id'], item['message_id'], item.get('date', ''))
            self.repo.update_follow_progress(chat_id, last_message_id=item['message_id'], last_event_at=now_ts(), last_error='')
            if download_media and self.downloader and item.get('media_kind'):
                self.downloader.enqueue_from_item(item, priority=10)

        gap_task = asyncio.create_task(gap_loop())
        try:
            await self.client.run_until_disconnected()
        finally:
            gap_task.cancel()
            with contextlib.suppress(Exception):
                await gap_task
