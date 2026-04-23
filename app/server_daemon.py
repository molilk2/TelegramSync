from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any, Awaitable, Callable

from telethon import events, utils

from app.config.config import load_config
from app.core.downloader import DownloadManager
from app.core.normalizer import normalize_message
from app.core.sync import SyncService
from app.ipc import read_message, write_message
from app.server_helpers import extract_dialog_name, extract_username, row_value
from app.utils import now_ts


class TelegramDaemon:
    def __init__(self, client, repo, logger, *, host: str, port: int, check_interval: int = 120, worker_poll_interval: int = 3):
        self.client = client
        self.repo = repo
        self.logger = logger
        self.host = host
        self.port = port
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval
        self.downloader = DownloadManager(repo, logger, should_stop=self.is_stopping)
        self.syncer = SyncService(client, repo, logger, self.downloader, should_stop=self.is_stopping)
        self.stop_event = asyncio.Event()
        self.server: asyncio.base_events.Server | None = None
        self.entity_cache: dict[int, Any] = {}
        self.operation_lock = asyncio.Lock()
        cfg = load_config()
        self.rpc_token = str(cfg.get('rpc', {}).get('token') or '').strip()
        self.mirror_cfg = cfg.get('mirror', {})
        self.command_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            'ping': self._cmd_ping,
            'stop': self._cmd_stop,
            'status': self._cmd_status,
            'whoami': self._cmd_whoami,
            'dialogs': self._cmd_dialogs,
            'dialogs.cached': self._cmd_dialogs_cached,
            'sync': self._cmd_sync,
            'backfill-media': self._cmd_backfill_media,
            'follow.add': self._cmd_follow_add,
            'follow.list': self._cmd_follow_list,
            'follow.remove': self._cmd_follow_remove,
            'follow.enable': self._cmd_follow_enable,
            'follow.disable': self._cmd_follow_disable,
            'follow.download': self._cmd_follow_download,
        }

    def is_stopping(self) -> bool:
        return self.stop_event.is_set()

    async def _resolve_follow_entity(self, row) -> Any:
        chat_id = int(row_value(row, 'chat_id', 0) or 0)
        cached = self.entity_cache.get(chat_id)
        if cached is not None:
            return cached

        peer_id = row_value(row, 'peer_id')
        username = str(row_value(row, 'username', '') or '').strip()
        entity_ref = str(row_value(row, 'entity_ref', '') or '').strip()

        candidates: list[str] = []
        if peer_id not in (None, '', 0, '0'):
            candidates.append(str(peer_id))
        if username:
            candidates.append(username)
        if entity_ref and not entity_ref.startswith(('Channel(', 'Chat(', 'User(')):
            candidates.append(entity_ref)
        if chat_id:
            candidates.append(f'-100{chat_id}')
            candidates.append(str(chat_id))

        last_exc = None
        for ref in candidates:
            try:
                entity = await self.syncer._resolve_entity(ref)
                self.entity_cache[chat_id] = entity
                return entity
            except Exception as exc:
                last_exc = exc

        raise RuntimeError(f'无法重新定位该会话 chat_id={chat_id}，建议先用 dialogs 确认后重新添加 follow。原始错误: {last_exc}')

    async def _ingest_message(self, msg):
        try:
            chat = await msg.get_chat()
        except Exception:
            chat = None
        try:
            sender = await msg.get_sender()
        except Exception:
            sender = None
        item = normalize_message(chat, msg, sender)
        follow = await self.repo.get_follow(item['chat_id'])
        if not follow or not bool(follow['follow_enabled']):
            return
        await self.repo.ingest_message(
            item,
            follow_row=follow,
            enqueue_download=bool(follow['download_media'] and item.get('media_kind')),
            download_priority=10,
            ensure_follow=True,
        )
        await self.repo.set_server_state('running', '收到新消息', last_message_at=now_ts(), last_error='')
        self.logger.info('新消息 chat_id=%s message_id=%s text=%s', item['chat_id'], item['message_id'], (item.get('text') or '').replace('\n', ' ')[:80])

    async def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            await self.repo.set_server_state('running', f'server 在线 {self.host}:{self.port}', pid=os.getpid(), last_heartbeat_at=now_ts(), last_error='')
            await asyncio.sleep(30)

    async def _download_loop(self, worker_name: str):
        while not self.stop_event.is_set():
            try:
                handled = await self.downloader.process_one_job(self.client)
                if not handled:
                    await asyncio.sleep(self.worker_poll_interval)
            except Exception as exc:
                await self.repo.set_server_state('running', f'下载 worker 异常，准备重试 [{worker_name}]', last_error=str(exc))
                self.logger.exception('下载 worker 异常 worker=%s', worker_name)
                await asyncio.sleep(5)

    async def _reclaim_stale_download_jobs_loop(self):
        while not self.stop_event.is_set():
            try:
                stale_after = int(self.mirror_cfg.get('download_stale_after_seconds', 900) or 900)
                reclaimed = await self.repo.reclaim_stale_download_jobs(stale_after)
                if reclaimed:
                    self.logger.warning('已回收卡死下载任务 %s 个', reclaimed)
                    await self.repo.set_server_state('running', f'已回收卡死下载任务 {reclaimed} 个', last_error='')
            except Exception as exc:
                self.logger.exception('回收卡死下载任务失败')
                await self.repo.set_server_state('running', '回收卡死下载任务失败', last_error=str(exc))
            await asyncio.sleep(60)

    async def _gap_check_loop(self, sync_missed_first: bool):
        initial = sync_missed_first
        while not self.stop_event.is_set():
            rows = await self.repo.list_follows(enabled_only=True)
            if not rows:
                await self.repo.set_server_state('running', '暂无 follow 主体，等待 cli 添加', last_gap_check_at=now_ts(), last_error='')
                await asyncio.sleep(self.check_interval)
                continue
            if not initial:
                await asyncio.sleep(self.check_interval)
            initial = False
            for row in rows:
                if self.stop_event.is_set():
                    break
                chat_id = int(row_value(row, 'chat_id', 0) or 0)
                try:
                    entity = await self._resolve_follow_entity(row)
                    state = await self.repo.get_chat_state(chat_id)
                    after_id = int((state['last_message_id'] if state else 0) or 0)
                    await self.syncer.sync_chat(
                        entity,
                        resume=True,
                        after_id=after_id,
                        download_media=bool(row_value(row, 'download_media', 0)),
                        register_follow=True,
                    )
                    await self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_sync_at=now_ts(), last_error='')
                    await self.repo.set_server_state('running', '周期补漏完成', last_gap_check_at=now_ts(), last_error='')
                except Exception as exc:
                    self.entity_cache.pop(chat_id, None)
                    await self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error=str(exc))
                    await self.repo.set_server_state('running', '周期补漏异常', last_gap_check_at=now_ts(), last_error=str(exc))
                    self.logger.exception('周期补漏失败 chat_id=%s', chat_id)

    async def _rpc_result(self, ok: bool, *, data=None, error: str = '') -> dict[str, Any]:
        if ok:
            return {'ok': True, 'data': data}
        return {'ok': False, 'error': error}

    async def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        cmd = str(payload.get('cmd') or '').strip()
        if not cmd:
            return await self._rpc_result(False, error='missing cmd')
        handler = self.command_handlers.get(cmd)
        if handler is None:
            return await self._rpc_result(False, error=f'unknown cmd: {cmd}')
        return await handler(payload)

    async def _cmd_ping(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._rpc_result(True, data={'message': 'pong'})

    async def _cmd_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.stop_event.set()
        if self.server is not None:
            self.server.close()
        await self.repo.set_server_state('stopping', '收到 stop 命令', last_heartbeat_at=now_ts())
        return await self._rpc_result(True, data={'message': 'server stopping'})

    async def _cmd_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._rpc_result(True, data=await self.collect_status(chat_id=int(payload.get('chat_id') or 0)))

    async def _cmd_whoami(self, payload: dict[str, Any]) -> dict[str, Any]:
        me = await self.client.get_me()
        return await self._rpc_result(True, data={
            'id': getattr(me, 'id', ''),
            'username': getattr(me, 'username', '') or '',
            'name': ' '.join([p for p in [getattr(me, 'first_name', ''), getattr(me, 'last_name', '')] if p]),
            'phone': getattr(me, 'phone', '') or '',
        })

    async def _cmd_dialogs(self, payload: dict[str, Any]) -> dict[str, Any]:
        dialogs = await self.syncer.list_dialogs(limit=int(payload.get('limit') or 50))
        return await self._rpc_result(True, data={'dialogs': dialogs})

    async def _cmd_dialogs_cached(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(r) for r in await self.repo.list_dialog_cache(limit=int(payload.get('limit') or 200))]
        return await self._rpc_result(True, data={'dialogs': rows})

    async def _cmd_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.operation_lock:
            result = await self.syncer.sync_chat(
                payload.get('chat'),
                limit=int(payload.get('limit') or 0),
                resume=not bool(payload.get('no_resume')),
                oldest_first=not bool(payload.get('newest_first')),
                after_id=int(payload.get('after_id') or 0),
                download_media=bool(payload.get('download_media')),
                register_follow=True,
            )
            return await self._rpc_result(True, data=result)

    async def _cmd_backfill_media(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.operation_lock:
            count = await self.syncer.backfill_media(chat_id=int(payload.get('chat_id') or 0) or None, limit=int(payload.get('limit') or 1000))
            return await self._rpc_result(True, data={'count': count})

    async def _cmd_follow_add(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.operation_lock:
            result = await self.syncer.follow_chat(
                str(payload.get('chat')),
                download_media=bool(payload.get('download_media')),
                check_interval=self.check_interval,
            )
            chat = await self.syncer._resolve_entity(str(payload.get('chat')))
            self.entity_cache[int(result.get('chat_id') or 0)] = chat
            return await self._rpc_result(True, data=result)

    async def _cmd_follow_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(r) for r in await self.repo.list_follows(enabled_only=False)]
        return await self._rpc_result(True, data={'follows': rows})

    async def _cmd_follow_remove(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_id = int(payload.get('chat_id') or 0)
        row = await self.repo.get_follow(chat_id)
        if not row:
            return await self._rpc_result(False, error=f'follow not found: {chat_id}')
        await self.repo.remove_follow(chat_id)
        self.entity_cache.pop(chat_id, None)
        return await self._rpc_result(True, data={'removed': chat_id})

    async def _cmd_follow_enable(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_id = int(payload.get('chat_id') or 0)
        row = await self.repo.get_follow(chat_id)
        if not row:
            return await self._rpc_result(False, error=f'follow not found: {chat_id}')
        await self.repo.set_follow_enabled(chat_id, True)
        return await self._rpc_result(True, data={'chat_id': chat_id, 'follow_enabled': True})

    async def _cmd_follow_disable(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_id = int(payload.get('chat_id') or 0)
        row = await self.repo.get_follow(chat_id)
        if not row:
            return await self._rpc_result(False, error=f'follow not found: {chat_id}')
        await self.repo.set_follow_enabled(chat_id, False)
        return await self._rpc_result(True, data={'chat_id': chat_id, 'follow_enabled': False})

    async def _cmd_follow_download(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_id = int(payload.get('chat_id') or 0)
        enabled = bool(payload.get('enabled'))
        row = await self.repo.get_follow(chat_id)
        if not row:
            return await self._rpc_result(False, error=f'follow not found: {chat_id}')
        await self.repo.set_follow_download_media(chat_id, enabled)
        return await self._rpc_result(True, data={'chat_id': chat_id, 'download_media': enabled})

    async def collect_status(self, *, chat_id: int = 0) -> dict[str, Any]:
        stats, mirror, server, dbs, runs, jobs = await asyncio.gather(
            self.repo.stats(),
            self.repo.get_mirror_state(),
            self.repo.get_server_state(),
            self.repo.db_file_stats(),
            self.repo.recent_runs(10),
            self.repo.recent_download_jobs(10),
        )
        out = {
            'stats': stats,
            'mirror': dict(mirror) if mirror else None,
            'server': dict(server) if server else None,
            'db': dbs,
            'runs': [dict(r) for r in runs],
            'download_jobs': [dict(r) for r in jobs],
        }
        if chat_id:
            row = await self.repo.get_follow(chat_id)
            out['follow'] = dict(row) if row else None
        return out

    async def _handle_new_message(self, event):
        try:
            await self._ingest_message(event.message)
        except Exception as exc:
            await self.repo.set_server_state('running', '消息处理异常', last_error=str(exc))
            self.logger.exception('消息处理异常')

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            try:
                payload = await read_message(reader)
            except ValueError as exc:
                await write_message(writer, {'ok': False, 'error': str(exc)})
                return
            if payload is None:
                return
            token = str(payload.get('token') or '').strip()
            if not self.rpc_token or token != self.rpc_token:
                await write_message(writer, {'ok': False, 'error': 'rpc authentication failed'})
                return
            try:
                resp = await self.handle_command(payload)
            except Exception as exc:
                self.logger.exception('处理 cli 命令失败')
                resp = {'ok': False, 'error': str(exc)}
            await write_message(writer, resp)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def run(self, *, sync_missed_first: bool = True):
        started_at = now_ts()
        await self.repo.set_server_state(
            'running',
            f'server 启动中 {self.host}:{self.port}',
            pid=os.getpid(),
            started_at=started_at,
            last_heartbeat_at=started_at,
            last_gap_check_at=0,
            last_message_at=0,
            last_error='',
        )

        self.client.add_event_handler(self._handle_new_message, events.NewMessage)

        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.logger.info('CLI 控制端口已启动 %s:%s', self.host, self.port)
        await self.repo.set_server_state('running', f'监听中 {self.host}:{self.port}', pid=os.getpid(), last_heartbeat_at=started_at, last_error='')

        self.downloader.refresh_config()
        self.mirror_cfg = load_config().get('mirror', {})
        worker_count = max(1, int(self.mirror_cfg.get('download_worker_count', 2) or 2))
        stale_after = int(self.mirror_cfg.get('download_stale_after_seconds', 900) or 900)
        reclaimed = await self.repo.reclaim_stale_download_jobs(stale_after)
        if reclaimed:
            self.logger.warning('启动时已回收卡死下载任务 %s 个', reclaimed)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        reclaim_task = asyncio.create_task(self._reclaim_stale_download_jobs_loop())
        download_tasks = [asyncio.create_task(self._download_loop(f'dl-{i + 1}')) for i in range(worker_count)]
        gap_task = asyncio.create_task(self._gap_check_loop(sync_missed_first))
        stop_note = 'server 已停止'
        try:
            await self.stop_event.wait()
        except asyncio.CancelledError:
            stop_note = 'server 收到取消信号，正在退出'
            self.stop_event.set()
            self.logger.info('server 主循环收到取消信号，开始优雅退出')
        finally:
            await self.repo.set_server_state('stopping', 'server 正在停止', last_heartbeat_at=now_ts())
            tasks = [heartbeat_task, reclaim_task, gap_task, *download_tasks]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                self.client.remove_event_handler(self._handle_new_message, events.NewMessage)
            if self.server:
                self.server.close()
                with contextlib.suppress(Exception):
                    await self.server.wait_closed()
            if self.client.is_connected():
                with contextlib.suppress(Exception):
                    await self.client.disconnect()
            await self.repo.set_server_state('stopped', stop_note, last_heartbeat_at=now_ts())
