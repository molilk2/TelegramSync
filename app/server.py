from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from getpass import getpass
from typing import Any

from telethon import events, utils
from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError

from app.config.config import load_config, save_config, default_config
from app.config.paths import SESSION_FILE
from app.core.downloader import DownloadManager
from app.core.normalizer import normalize_message
from app.core.session import SessionManager
from app.config.paths import DB_FILE
from app.errors import friendly_error_message, format_command_usage_error
from app.logging_setup import setup_logging
from app.store.db import DB
from app.store.repo import Repo
from app.core.sync import SyncService
from app.ipc import read_message, write_message
from app.utils import now_ts

logger = setup_logging()



def _row_has(row, key: str) -> bool:
    try:
        if hasattr(row, 'keys'):
            return key in row.keys()
    except Exception:
        pass
    try:
        row[key]
        return True
    except Exception:
        return False


def _row_value(row, key: str, default=None):
    try:
        value = row[key]
    except Exception:
        return default
    return default if value is None else value


def interactive_server_setup(*, api_id: int = 0, api_hash: str = '', host: str = '', port: int = 0):
    cfg = load_config()
    tg = cfg.setdefault('telegram', {})
    rpc = cfg.setdefault('rpc', {})

    current_api_id = str(api_id or tg.get('api_id') or '').strip()
    current_api_hash = str(api_hash or tg.get('api_hash') or '').strip()
    current_host = str(host or rpc.get('host') or '127.0.0.1').strip()
    current_port = str(port or rpc.get('port') or 6389).strip()

    val = input(f'请输入 Telegram api_id [{current_api_id}]: ').strip()
    tg['api_id'] = int(val or current_api_id or 0)

    masked_hash = ('*' * min(len(current_api_hash), 8)) if current_api_hash else ''
    val = input(f'请输入 Telegram api_hash [{masked_hash}]: ').strip()
    tg['api_hash'] = val or current_api_hash

    val = input(f'请输入本地 RPC host [{current_host}]: ').strip()
    rpc['host'] = val or current_host

    val = input(f'请输入本地 RPC port [{current_port}]: ').strip()
    rpc['port'] = int(val or current_port or 6389)

    save_config(cfg)
    return cfg


def config_is_initialized() -> bool:
    cfg = load_config()
    tg = cfg.get('telegram', {})
    return bool(str(tg.get('api_id') or '').strip() and str(tg.get('api_hash') or '').strip())


async def cache_account_dialogs(client, repo, logger, *, limit: int = 0) -> int:
    count = 0
    repo.clear_dialog_cache()
    async for dialog in client.iter_dialogs(limit=None if int(limit or 0) <= 0 else int(limit)):
        entity = dialog.entity
        chat_id = int(getattr(entity, 'id', 0) or 0)
        try:
            peer_id = utils.get_peer_id(entity)
        except Exception:
            peer_id = chat_id
        entity_type = 'channel' if dialog.is_channel else ('group' if dialog.is_group else 'user')
        repo.save_dialog_cache(chat_id=chat_id, peer_id=peer_id, chat_name=dialog.name or '', username=getattr(entity, 'username', None) or '', entity_type=entity_type)
        count += 1
    logger.info('已缓存 %s 个会话/频道', count)
    return count


def server_logout() -> bool:
    try:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
            return True
    except Exception:
        pass
    return False


async def ensure_server_login(*, phone: str = '', api_id: int = 0, api_hash: str = ''):
    cfg = load_config()
    tg = cfg.setdefault('telegram', {})
    if api_id:
        tg['api_id'] = int(api_id)
    if api_hash:
        tg['api_hash'] = str(api_hash).strip()
    if not tg.get('api_id'):
        val = input('请输入 Telegram api_id: ').strip()
        if val:
            tg['api_id'] = int(val)
    if not tg.get('api_hash'):
        tg['api_hash'] = input('请输入 Telegram api_hash: ').strip()
    save_config(cfg)

    manager = SessionManager()
    client = manager.build_client()
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        return manager, client, me

    phone = phone.strip() or input('请输入 Telegram 登录手机号（带国家区号）: ').strip()
    if not phone:
        raise RuntimeError('未提供手机号，无法完成登录。')
    sent = await client.send_code_request(phone)
    for _ in range(3):
        code = input('请输入收到的验证码: ').strip()
        if not code:
            print('验证码不能为空。')
            continue
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            me = await client.get_me()
            return manager, client, me
        except SessionPasswordNeededError:
            password = getpass('该账号开启了两步验证，请输入密码: ')
            await client.sign_in(password=password)
            me = await client.get_me()
            return manager, client, me
        except PhoneCodeInvalidError:
            print('验证码错误，请重试。')
    raise RuntimeError('验证码连续错误次数过多，登录未完成。')


class TelegramDaemon:
    def __init__(self, client, repo, logger, *, host: str, port: int, check_interval: int = 120, worker_poll_interval: int = 3):
        self.client = client
        self.repo = repo
        self.logger = logger
        self.host = host
        self.port = port
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval
        self.downloader = DownloadManager(repo, logger)
        self.syncer = SyncService(client, repo, logger, self.downloader)
        self.stop_event = asyncio.Event()
        self.server: asyncio.base_events.Server | None = None
        self.entity_cache: dict[int, Any] = {}
        self.operation_lock = asyncio.Lock()

    async def _resolve_follow_entity(self, row) -> Any:
        chat_id = int(_row_value(row, 'chat_id', 0) or 0)
        cached = self.entity_cache.get(chat_id)
        if cached is not None:
            return cached

        peer_id = _row_value(row, 'peer_id')
        username = str(_row_value(row, 'username', '') or '').strip()
        entity_ref = str(_row_value(row, 'entity_ref', '') or '').strip()

        candidates: list[str] = []
        if peer_id not in (None, '', 0, '0'):
            candidates.append(str(peer_id))
        if username:
            candidates.append(username)
        if entity_ref and not entity_ref.startswith('Channel(') and not entity_ref.startswith('Chat(') and not entity_ref.startswith('User('):
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
        follow = self.repo.get_follow(item['chat_id'])
        if not follow or not bool(follow['follow_enabled']):
            return
        self.repo.save_message(item)
        self.repo.update_chat_state(item['chat_id'], item['message_id'], item.get('date', ''))
        self.repo.update_follow_progress(item['chat_id'], last_message_id=item['message_id'], last_event_at=now_ts(), last_error='', chat_name=item['chat_name'])
        self.repo.set_server_state('running', '收到新消息', last_message_at=now_ts(), last_error='')
        if bool(follow['download_media']) and item.get('media_kind'):
            self.downloader.enqueue_from_item(item, priority=10)
        self.logger.info('新消息 chat_id=%s message_id=%s text=%s', item['chat_id'], item['message_id'], (item.get('text') or '').replace('\n', ' ')[:80])

    async def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            self.repo.set_server_state('running', f'server 在线 {self.host}:{self.port}', pid=os.getpid(), last_heartbeat_at=now_ts(), last_error='')
            await asyncio.sleep(30)

    async def _download_loop(self):
        while not self.stop_event.is_set():
            try:
                handled = await self.downloader.process_one_job(self.client)
                if not handled:
                    await asyncio.sleep(self.worker_poll_interval)
            except Exception as exc:
                self.repo.set_server_state('running', '下载 worker 异常，准备重试', last_error=str(exc))
                self.logger.exception('下载 worker 异常')
                await asyncio.sleep(5)

    async def _gap_check_loop(self, sync_missed_first: bool):
        initial = sync_missed_first
        while not self.stop_event.is_set():
            rows = self.repo.list_follows(enabled_only=True)
            if not rows:
                self.repo.set_server_state('running', '暂无 follow 主体，等待 cli 添加', last_gap_check_at=now_ts(), last_error='')
                await asyncio.sleep(self.check_interval)
                continue
            if not initial:
                await asyncio.sleep(self.check_interval)
            initial = False
            for row in rows:
                if self.stop_event.is_set():
                    break
                chat_id = int(_row_value(row, 'chat_id', 0) or 0)
                try:
                    entity = await self._resolve_follow_entity(row)
                    state = self.repo.get_chat_state(chat_id)
                    after_id = int((state['last_message_id'] if state else 0) or 0)
                    await self.syncer.sync_chat(entity, resume=True, after_id=after_id, download_media=bool(_row_value(row, 'download_media', 0)), register_follow=True)
                    self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_sync_at=now_ts(), last_error='')
                    self.repo.set_server_state('running', '周期补漏完成', last_gap_check_at=now_ts(), last_error='')
                except Exception as exc:
                    self.entity_cache.pop(chat_id, None)
                    self.repo.update_follow_progress(chat_id, last_gap_check_at=now_ts(), last_error=str(exc))
                    self.repo.set_server_state('running', '周期补漏异常', last_gap_check_at=now_ts(), last_error=str(exc))
                    self.logger.exception('周期补漏失败 chat_id=%s', chat_id)

    async def _rpc_result(self, ok: bool, *, data=None, error: str = '') -> dict[str, Any]:
        if ok:
            return {'ok': True, 'data': data}
        return {'ok': False, 'error': error}

    async def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        cmd = str(payload.get('cmd') or '').strip()
        if not cmd:
            return await self._rpc_result(False, error='missing cmd')
        if cmd == 'ping':
            return await self._rpc_result(True, data={'message': 'pong'})
        if cmd == 'stop':
            self.stop_event.set()
            self.repo.set_server_state('stopping', '收到 stop 命令', last_heartbeat_at=now_ts())
            return await self._rpc_result(True, data={'message': 'server stopping'})
        if cmd == 'status':
            return await self._rpc_result(True, data=self.collect_status(chat_id=int(payload.get('chat_id') or 0)))
        if cmd == 'whoami':
            me = await self.client.get_me()
            return await self._rpc_result(True, data={
                'id': getattr(me, 'id', ''),
                'username': getattr(me, 'username', '') or '',
                'name': ' '.join([p for p in [getattr(me, 'first_name', ''), getattr(me, 'last_name', '')] if p]),
                'phone': getattr(me, 'phone', '') or '',
            })
        if cmd == 'dialogs':
            dialogs = await self.syncer.list_dialogs(limit=int(payload.get('limit') or 50))
            return await self._rpc_result(True, data={'dialogs': dialogs})
        if cmd == 'dialogs.cached':
            rows = [dict(r) for r in self.repo.list_dialog_cache(limit=int(payload.get('limit') or 200))]
            return await self._rpc_result(True, data={'dialogs': rows})
        if cmd == 'sync':
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
        if cmd == 'backfill-media':
            async with self.operation_lock:
                count = await self.syncer.backfill_media(chat_id=int(payload.get('chat_id') or 0) or None, limit=int(payload.get('limit') or 1000))
                return await self._rpc_result(True, data={'count': count})
        if cmd == 'follow.add':
            async with self.operation_lock:
                chat = await self.syncer._resolve_entity(str(payload.get('chat')))
                peer_id = utils.get_peer_id(chat)
                chat_id = int(getattr(chat, 'id', 0))
                chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(peer_id)
                self.entity_cache[chat_id] = chat
                self.repo.upsert_follow(chat_id=chat_id, peer_id=peer_id, chat_name=chat_name, entity_ref='', username=getattr(chat, 'username', None) or '', follow_enabled=True, download_media=bool(payload.get('download_media')))
                return await self._rpc_result(True, data={'chat_id': chat_id, 'peer_id': peer_id, 'chat_name': chat_name})
        if cmd == 'follow.list':
            rows = [dict(r) for r in self.repo.list_follows(enabled_only=False)]
            return await self._rpc_result(True, data={'follows': rows})
        if cmd == 'follow.remove':
            chat_id = int(payload.get('chat_id') or 0)
            self.repo.remove_follow(chat_id)
            self.entity_cache.pop(chat_id, None)
            return await self._rpc_result(True, data={'chat_id': chat_id})
        if cmd == 'follow.enable':
            chat_id = int(payload.get('chat_id') or 0)
            self.repo.set_follow_enabled(chat_id, True)
            return await self._rpc_result(True, data={'chat_id': chat_id, 'enabled': True})
        if cmd == 'follow.disable':
            chat_id = int(payload.get('chat_id') or 0)
            self.repo.set_follow_enabled(chat_id, False)
            return await self._rpc_result(True, data={'chat_id': chat_id, 'enabled': False})
        if cmd == 'follow.download':
            chat_id = int(payload.get('chat_id') or 0)
            enabled = bool(payload.get('enabled'))
            self.repo.set_follow_download_media(chat_id, enabled)
            return await self._rpc_result(True, data={'chat_id': chat_id, 'download_media': enabled})
        return await self._rpc_result(False, error=f'unknown cmd: {cmd}')

    def collect_status(self, *, chat_id: int = 0) -> dict[str, Any]:
        stats = self.repo.stats()
        mirror = self.repo.get_mirror_state()
        server = self.repo.get_server_state()
        dbs = self.repo.db_file_stats()
        out = {
            'stats': stats,
            'mirror': dict(mirror) if mirror else None,
            'server': dict(server) if server else None,
            'db': dbs,
            'runs': [dict(r) for r in self.repo.recent_runs(10)],
            'download_jobs': [dict(r) for r in self.repo.recent_download_jobs(10)],
        }
        if chat_id:
            row = self.repo.get_follow(chat_id)
            out['follow'] = dict(row) if row else None
        return out

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            payload = await read_message(reader)
            if payload is None:
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
        self.repo.set_server_state('running', f'server 启动中 {self.host}:{self.port}', pid=os.getpid(), started_at=started_at, last_heartbeat_at=started_at, last_gap_check_at=0, last_message_at=0, last_error='')

        @self.client.on(events.NewMessage)
        async def on_new_message(event):
            await self._ingest_message(event.message)

        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.logger.info('CLI 控制端口已启动 %s:%s', self.host, self.port)
        self.repo.set_server_state('running', f'监听中 {self.host}:{self.port}', pid=os.getpid(), last_heartbeat_at=started_at, last_error='')

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        download_task = asyncio.create_task(self._download_loop())
        gap_task = asyncio.create_task(self._gap_check_loop(sync_missed_first))
        try:
            await self.stop_event.wait()
        finally:
            heartbeat_task.cancel()
            download_task.cancel()
            gap_task.cancel()
            for task in (heartbeat_task, download_task, gap_task):
                with contextlib.suppress(Exception):
                    await task
            if self.server:
                self.server.close()
                await self.server.wait_closed()
            if self.client.is_connected():
                await self.client.disconnect()
            self.repo.set_server_state('stopped', 'server 已停止', last_heartbeat_at=now_ts())



async def interactive_server_menu(*, repo, logger, host: str, port: int, check_interval: int, worker_poll_interval: int, phone: str = '', api_id: int = 0, api_hash: str = '') -> int:
    if not config_is_initialized():
        print('检测到 server 尚未初始化，先进行配置。')
        interactive_server_setup(api_id=api_id, api_hash=api_hash, host=host, port=port)
    manager, client, me = await ensure_server_login(phone=phone, api_id=api_id, api_hash=api_hash)
    try:
        count = await cache_account_dialogs(client, repo, logger)
        who = getattr(me, 'username', None) or getattr(me, 'first_name', None) or getattr(me, 'id', 'unknown')
        print(f'当前账号: {who}')
        print(f'已缓存会话: {count}')
    finally:
        if client.is_connected():
            await client.disconnect()

    while True:
        print('\n=== Server 菜单 ===')
        print('1. 启动服务')
        print('2. 更改配置')
        print('3. 退出登录')
        print('4. 优化数据库')
        print('5. 刷新会话缓存')
        print('0. 返回')
        choice = input('请选择: ').strip()
        if choice == '1':
            await run_server_process(repo=repo, logger=logger, host=host, port=port, check_interval=check_interval, worker_poll_interval=worker_poll_interval, sync_missed_first=True, phone=phone, api_id=api_id, api_hash=api_hash)
            return 0
        if choice == '2':
            cfg = interactive_server_setup(api_id=api_id, api_hash=api_hash, host=host, port=port)
            host = cfg.get('rpc', {}).get('host') or host
            port = int(cfg.get('rpc', {}).get('port') or port)
            print('配置已更新。')
            continue
        if choice == '3':
            ok = server_logout()
            print('已退出登录并删除会话文件。' if ok else '当前没有可删除的会话文件。')
            return 0
        if choice == '4':
            stats = repo.optimize_database()
            print('数据库优化完成。')
            print('DB 主文件大小:', stats.get('db_size', 0))
            print('DB WAL 大小 :', stats.get('wal_size', 0))
            continue
        if choice == '5':
            manager, client, me = await ensure_server_login(phone=phone, api_id=api_id, api_hash=api_hash)
            try:
                count = await cache_account_dialogs(client, repo, logger)
                print(f'已刷新缓存，共 {count} 个会话。')
            finally:
                if client.is_connected():
                    await client.disconnect()
            continue
        if choice == '0':
            return 0
        print('无效选择，请重试。')


async def run_server_process(*, repo, logger, host: str, port: int, check_interval: int, worker_poll_interval: int,
                             sync_missed_first: bool, phone: str = '', api_id: int = 0, api_hash: str = ''):
    manager, client, me = await ensure_server_login(phone=phone, api_id=api_id, api_hash=api_hash)
    logger.info('server 登录账号: %s', getattr(me, 'username', None) or getattr(me, 'first_name', None) or getattr(me, 'id', 'unknown'))
    try:
        await cache_account_dialogs(client, repo, logger)
    except Exception:
        logger.exception('缓存账号会话失败')
    daemon = TelegramDaemon(client, repo, logger, host=host, port=port, check_interval=check_interval, worker_poll_interval=worker_poll_interval)
    await daemon.run(sync_missed_first=sync_missed_first)


class FriendlyServerArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print('错误：' + format_command_usage_error(message), file=sys.stderr)
        print('', file=sys.stderr)
        self.print_help(sys.stderr)
        raise SystemExit(2)


def build_server_parser() -> argparse.ArgumentParser:
    parser = FriendlyServerArgumentParser(prog='tg-server', description='Telegram server 侧入口')
    sub = parser.add_subparsers(dest='server_cmd', required=False)

    p_setup = sub.add_parser('setup', help='在 server 侧写入 API / RPC 配置，可交互输入')
    p_setup.add_argument('--api-id', type=int, default=0)
    p_setup.add_argument('--api-hash', default='')
    p_setup.add_argument('--host', default='')
    p_setup.add_argument('--port', type=int, default=0)

    p_login = sub.add_parser('login', help='在 server 侧完成登录并缓存一次会话')
    p_login.add_argument('--api-id', type=int, default=0)
    p_login.add_argument('--api-hash', default='')
    p_login.add_argument('--phone', default='')

    p_run = sub.add_parser('run', help='启动常驻 server')
    p_run.add_argument('--host', default='')
    p_run.add_argument('--port', type=int, default=0)
    p_run.add_argument('--phone', default='')
    p_run.add_argument('--api-id', type=int, default=0)
    p_run.add_argument('--api-hash', default='')
    p_run.add_argument('--check-interval', type=int, default=120)
    p_run.add_argument('--worker-poll-interval', type=int, default=3)
    p_run.add_argument('--no-sync-missed-first', action='store_true')

    sub.add_parser('logout', help='删除本地会话文件并退出登录')
    sub.add_parser('optimize-db', help='执行 WAL checkpoint 与 VACUUM')
    return parser


def _get_server_host_port(args=None):
    cfg = load_config()
    rpc = cfg.get('rpc', {})
    host = getattr(args, 'host', '') or rpc.get('host') or '127.0.0.1'
    port = int(getattr(args, 'port', 0) or rpc.get('port') or 6389)
    return host, port


async def dispatch_server_async(args) -> int:
    host, port = _get_server_host_port(args)
    repo = Repo(DB(DB_FILE))

    if not getattr(args, 'server_cmd', None):
        return await interactive_server_menu(
            repo=repo,
            logger=logger,
            host=host,
            port=port,
            check_interval=120,
            worker_poll_interval=3,
            phone=getattr(args, 'phone', ''),
            api_id=getattr(args, 'api_id', 0),
            api_hash=getattr(args, 'api_hash', ''),
        )

    if args.server_cmd == 'setup':
        cfg = interactive_server_setup(api_id=args.api_id, api_hash=args.api_hash, host=args.host, port=args.port)
        print('server 配置已更新。')
        print('telegram.api_id :', cfg.get('telegram', {}).get('api_id') or '')
        print('telegram.api_hash 已保存:', bool(cfg.get('telegram', {}).get('api_hash')))
        print('rpc.host        :', cfg.get('rpc', {}).get('host') or '')
        print('rpc.port        :', cfg.get('rpc', {}).get('port') or '')
        return 0

    if args.server_cmd == 'login':
        _, client, me = await ensure_server_login(phone=args.phone, api_id=args.api_id, api_hash=args.api_hash)
        try:
            count = await cache_account_dialogs(client, repo, logger)
        finally:
            if client.is_connected():
                await client.disconnect()
        print('登录成功:', getattr(me, 'username', None) or getattr(me, 'first_name', None) or getattr(me, 'id', 'unknown'))
        print('已缓存会话:', count)
        return 0

    if args.server_cmd == 'logout':
        print('已退出登录并删除会话文件。' if server_logout() else '当前没有可删除的会话文件。')
        return 0

    if args.server_cmd == 'optimize-db':
        stats = repo.optimize_database()
        print('数据库优化完成。')
        print('DB 主文件大小:', stats.get('db_size', 0))
        print('DB WAL 大小 :', stats.get('wal_size', 0))
        return 0

    run_id = repo.create_run('server', f'{host}:{port}', note='server run 启动')
    try:
        await run_server_process(
            repo=repo,
            logger=logger,
            host=host,
            port=port,
            check_interval=args.check_interval,
            worker_poll_interval=args.worker_poll_interval,
            sync_missed_first=not args.no_sync_missed_first,
            phone=args.phone,
            api_id=args.api_id,
            api_hash=args.api_hash,
        )
        repo.finish_run(run_id, 'stopped', 'server 正常退出')
        return 0
    except KeyboardInterrupt:
        repo.finish_run(run_id, 'stopped', '用户手动停止')
        print('\nserver 已手动停止')
        return 0


def server_entry(argv: list[str] | None = None) -> int:
    parser = build_server_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(dispatch_server_async(args))
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception('执行失败')
        print('错误:', friendly_error_message(exc, action='执行命令'))
        return 1
