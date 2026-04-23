from __future__ import annotations

import argparse
import asyncio
import sys

from app.config.config import load_config
from app.config.paths import DB_FILE
from app.errors import friendly_error_message, format_command_usage_error
from app.logging_setup import setup_logging
from app.server_auth import (
    cache_account_dialogs,
    config_is_initialized,
    ensure_server_login,
    interactive_server_setup,
    server_logout,
)
from app.server_daemon import TelegramDaemon
from app.server_lock import ServerInstanceLock
from app.store.async_repo import AsyncRepo
from app.store.db import DB
from app.store.repo import Repo

logger = setup_logging()


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


async def interactive_server_menu(*, repo, logger, host: str, port: int, check_interval: int, worker_poll_interval: int, phone: str = '', api_id: int = 0, api_hash: str = '') -> int:
    if not config_is_initialized():
        print('检测到 server 尚未初始化，先进行配置。')
        interactive_server_setup(api_id=api_id, api_hash=api_hash, host=host, port=port)

    async_repo = AsyncRepo(repo)

    while True:
        print('\n=== Server 菜单 ===')
        print('1. 启动服务')
        print('2. 更改配置')
        print('3. 登录并刷新会话缓存')
        print('4. 退出登录')
        print('5. 优化数据库')
        print('0. 返回')
        choice = input('请选择: ').strip()

        if choice == '1':
            try:
                await run_server_process(
                    repo=async_repo,
                    logger=logger,
                    host=host,
                    port=port,
                    check_interval=check_interval,
                    worker_poll_interval=worker_poll_interval,
                    sync_missed_first=True,
                    phone=phone,
                    api_id=api_id,
                    api_hash=api_hash,
                )
            except KeyboardInterrupt:
                print('\nserver 已手动停止')
            return 0

        if choice == '2':
            cfg = interactive_server_setup(api_id=api_id, api_hash=api_hash, host=host, port=port)
            host = cfg.get('rpc', {}).get('host') or host
            port = int(cfg.get('rpc', {}).get('port') or port)
            print('配置已更新。')
            continue

        if choice == '3':
            _, client, me = await ensure_server_login(phone=phone, api_id=api_id, api_hash=api_hash)
            try:
                count = await cache_account_dialogs(client, async_repo, logger)
                print('登录成功:', getattr(me, 'username', None) or getattr(me, 'first_name', None) or getattr(me, 'id', 'unknown'))
                print('已缓存会话:', count)
            finally:
                if client.is_connected():
                    await client.disconnect()
            continue

        if choice == '4':
            ok = server_logout()
            print('已退出登录并删除会话文件。' if ok else '当前没有可删除的会话文件。')
            continue

        if choice == '5':
            stats = await async_repo.optimize_database()
            print('数据库优化完成。')
            print('DB 主文件大小:', stats.get('db_size', 0))
            print('DB WAL 大小 :', stats.get('wal_size', 0))
            continue

        if choice == '0':
            return 0

        print('无效选择，请重试。')


async def run_server_process(*, repo, logger, host: str, port: int, check_interval: int, worker_poll_interval: int,
                             sync_missed_first: bool, phone: str = '', api_id: int = 0, api_hash: str = ''):
    lock = ServerInstanceLock(host=host, port=port)
    lock.acquire()
    client = None
    try:
        _, client, me = await ensure_server_login(phone=phone, api_id=api_id, api_hash=api_hash)
        logger.info('server 登录账号: %s', getattr(me, 'username', None) or getattr(me, 'first_name', None) or getattr(me, 'id', 'unknown'))
        try:
            await cache_account_dialogs(client, repo, logger)
        except Exception:
            logger.exception('缓存账号会话失败')
        daemon = TelegramDaemon(client, repo, logger, host=host, port=port, check_interval=check_interval, worker_poll_interval=worker_poll_interval)
        await daemon.run(sync_missed_first=sync_missed_first)
    finally:
        lock.release()


async def dispatch_server_async(args) -> int:
    host, port = _get_server_host_port(args)
    sync_repo = Repo(DB(DB_FILE))
    repo = AsyncRepo(sync_repo)

    if not getattr(args, 'server_cmd', None):
        return await interactive_server_menu(
            repo=sync_repo,
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
        print('rpc.token 已保存:', bool(cfg.get('rpc', {}).get('token')))
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
        stats = await repo.optimize_database()
        print('数据库优化完成。')
        print('DB 主文件大小:', stats.get('db_size', 0))
        print('DB WAL 大小 :', stats.get('wal_size', 0))
        return 0

    run_id = await repo.create_run('server', f'{host}:{port}', note='server run 启动')
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
        await repo.finish_run(run_id, 'stopped', 'server 正常退出')
        return 0
    except KeyboardInterrupt:
        await repo.finish_run(run_id, 'stopped', '用户手动停止')
        print('\nserver 已手动停止')
        return 0


def server_entry(argv: list[str] | None = None) -> int:
    parser = build_server_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(dispatch_server_async(args))
    except KeyboardInterrupt:
        print('\nserver 已手动停止')
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception('执行失败')
        print('错误:', friendly_error_message(exc, action='执行命令'))
        return 1
