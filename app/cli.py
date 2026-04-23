from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.config.config import load_config
from app.config.paths import CONFIG_FILE, DATA_DIR, SESSION_FILE, DB_FILE, LOG_FILE, DOWNLOAD_DIR
from app.errors import friendly_error_message, format_command_usage_error
from app.ipc import send_request
from app.logging_setup import setup_logging

logger = setup_logging()


class FriendlyArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print('错误：' + format_command_usage_error(message), file=sys.stderr)
        print('', file=sys.stderr)
        self.print_help(sys.stderr)
        raise SystemExit(2)


def print_paths() -> None:
    print('CONFIG_FILE :', CONFIG_FILE)
    print('SESSION_FILE:', SESSION_FILE)
    print('DB_FILE     :', DB_FILE)
    print('LOG_FILE    :', LOG_FILE)
    print('DATA_DIR    :', DATA_DIR)
    print('DOWNLOAD_DIR:', DOWNLOAD_DIR)


def get_rpc_host_port(args=None):
    cfg = load_config()
    rpc = cfg.get('rpc', {})
    host = getattr(args, 'host', '') or rpc.get('host') or '127.0.0.1'
    port = int(getattr(args, 'port', 0) or rpc.get('port') or 6389)
    return host, port


def get_rpc_token() -> str:
    cfg = load_config()
    return str(cfg.get('rpc', {}).get('token') or '').strip()


def build_parser() -> argparse.ArgumentParser:
    parser = FriendlyArgumentParser(prog='tg-cli', description='Telegram CLI 控制端（仅连接已运行的 server）')
    parser.add_argument('--host', default='')
    parser.add_argument('--port', type=int, default=0)

    sub = parser.add_subparsers(dest='command', required=False)
    sub.add_parser('ping', help='测试 server 连通性')
    sub.add_parser('whoami', help='查看 server 当前登录账号')

    p_dialogs = sub.add_parser('dialogs', help='列出 server 最近会话')
    p_dialogs.add_argument('--limit', type=int, default=50)

    p_dialogs_cached = sub.add_parser('dialogs-cached', help='查看 server 缓存的会话')
    p_dialogs_cached.add_argument('--limit', type=int, default=200)

    p_sync = sub.add_parser('sync', help='由 server 执行历史同步；消息先入库，媒体异步入下载队列')
    p_sync.add_argument('--chat', required=True)
    p_sync.add_argument('--limit', type=int, default=0)
    p_sync.add_argument('--no-resume', action='store_true')
    p_sync.add_argument('--after-id', type=int, default=0)
    p_sync.add_argument('--newest-first', action='store_true')
    p_sync.add_argument('--download-media', action='store_true')

    p_follow = sub.add_parser('follow', help='管理 follow 主体')
    sub_follow = p_follow.add_subparsers(dest='follow_cmd', required=True)
    p_follow_add = sub_follow.add_parser('add', help='添加 follow')
    p_follow_add.add_argument('--chat', required=True)
    p_follow_add.add_argument('--download-media', action='store_true')
    p_follow_list = sub_follow.add_parser('list', help='列出 follow')
    p_follow_list.add_argument('--verbose', action='store_true')
    p_follow_remove = sub_follow.add_parser('remove', help='移除 follow')
    p_follow_remove.add_argument('--chat-id', type=int, required=True)
    p_follow_enable = sub_follow.add_parser('enable', help='启用 follow')
    p_follow_enable.add_argument('--chat-id', type=int, required=True)
    p_follow_disable = sub_follow.add_parser('disable', help='禁用 follow')
    p_follow_disable.add_argument('--chat-id', type=int, required=True)
    p_follow_dl = sub_follow.add_parser('download', help='切换 follow 下载开关')
    p_follow_dl.add_argument('--chat-id', type=int, required=True)
    p_follow_dl.add_argument('--enabled', choices=['true', 'false'], required=True)

    p_backfill = sub.add_parser('backfill-media', help='扫描历史消息，把缺失媒体补入下载队列')
    p_backfill.add_argument('--chat-id', type=int, default=0)
    p_backfill.add_argument('--limit', type=int, default=1000)

    p_status = sub.add_parser('status', help='查看 server 与数据库状态')
    p_status.add_argument('--chat-id', type=int, default=0)

    sub.add_parser('stop', help='让 server 优雅退出')
    sub.add_parser('menu', help='进入交互式 CLI 菜单')
    p_channels = sub.add_parser('channels', help='进入频道 / follow 交互管理')
    p_channels.add_argument('--dialogs-limit', type=int, default=100)

    p_logs = sub.add_parser('logs', help='查看日志尾部')
    p_logs.add_argument('--tail', type=int, default=100)
    sub.add_parser('paths', help='查看配置/数据库/session 路径')
    return parser


async def send_cli(payload: dict) -> dict:
    host = payload.pop('_host')
    port = payload.pop('_port')
    return await send_request(host, port, payload)


async def rpc_call(args, payload: dict[str, Any]) -> dict[str, Any]:
    host, port = get_rpc_host_port(args)
    req = {'_host': host, '_port': port, 'token': get_rpc_token()}
    req.update(payload)
    resp = await send_cli(req)
    if not resp.get('ok'):
        raise RuntimeError(friendly_error_message(resp.get('error') or 'server request failed', action='执行命令'))
    return resp.get('data') or {}


def format_dialog_label(item: dict) -> str:
    return (
        item.get('chat_name')
        or item.get('name')
        or item.get('username')
        or str(item.get('peer_id') or item.get('chat_id') or '-')
    )


def print_follow_rows(rows: list[dict], *, verbose: bool = False) -> None:
    if not rows:
        print('当前没有 follow 主体。')
        return
    for idx, item in enumerate(rows, 1):
        name = format_dialog_label(item)
        print(f'{idx:>3}. {name}')
        print(f'     chat_id : {item.get("chat_id", "-")}')
        print(f'     peer_id : {item.get("peer_id", "-")}')
        if item.get('username'):
            print(f'     username: {item.get("username")}')
        print(f'     状态    : {"启用" if item.get("follow_enabled") else "禁用"} / 下载 {"开" if item.get("download_media") else "关"}')
        if verbose:
            print('     原始    :', json.dumps(item, ensure_ascii=False))
        print()


def _print_status(data: dict):
    stats = data.get('stats', {})
    dbs = data.get('db') or {}
    print('总览状态')
    print('消息总数              :', stats.get('messages', 0))
    print('含媒体消息数          :', stats.get('messages_with_media', 0))
    print('已同步 chat 数        :', stats.get('chat_state', 0))
    print('follow 总数           :', stats.get('follows', 0))
    print('启用 follow 数        :', stats.get('follows_enabled', 0))
    print('启用下载的 follow 数  :', stats.get('follows_download_enabled', 0))
    print('下载队列 pending      :', stats.get('download_jobs_pending', 0))
    print('下载队列 downloading  :', stats.get('download_jobs_downloading', 0))
    print('下载队列 done         :', stats.get('download_jobs_done', 0))
    print('下载队列 failed       :', stats.get('download_jobs_failed', 0))
    print('DB 主文件大小         :', dbs.get('db_size', 0))
    print('DB WAL 大小           :', dbs.get('wal_size', 0))
    if data.get('server'):
        server = data['server']
        print('server 状态           :', server.get('status', '-'))
        print('server 说明           :', server.get('note', '-'))


async def interactive_cli_channels(args=None) -> int:
    base_args = args or argparse.Namespace(host='', port=0)
    while True:
        print('\n=== 频道 / Follow 管理 ===')
        print('1. 查看 follow 列表')
        print('2. 从缓存会话中添加 follow')
        print('3. 手动输入 chat 添加 follow')
        print('4. 启用/禁用下载开关')
        print('5. 移除 follow')
        print('6. 历史媒体补入下载队列')
        print('0. 返回')
        choice = input('请选择: ').strip()
        try:
            if choice == '1':
                data = await rpc_call(base_args, {'cmd': 'follow.list'})
                print_follow_rows(data.get('follows') or [])
                continue
            if choice == '2':
                data = await rpc_call(base_args, {'cmd': 'dialogs.cached', 'limit': 200})
                rows = data.get('dialogs') or []
                if not rows:
                    print('当前没有缓存会话，请先使用 tg-server login 或 tg-server 菜单刷新会话缓存。')
                    continue
                for i, row in enumerate(rows, 1):
                    print(f'{i:>3}. {format_dialog_label(row)}  peer_id={row.get("peer_id") or "-"}  username={row.get("username") or "-"}  type={row.get("entity_type") or "-"}')
                pick = input('输入序号（空返回）: ').strip()
                if not pick:
                    continue
                idx = int(pick) - 1
                if idx < 0 or idx >= len(rows):
                    print('序号无效。')
                    continue
                dl = input('下载媒体？[y/N]: ').strip().lower() in ('y', 'yes', '1')
                item = rows[idx]
                chat_ref = str(item.get('peer_id') or item.get('username') or item.get('chat_id'))
                out = await rpc_call(base_args, {'cmd': 'follow.add', 'chat': chat_ref, 'download_media': dl})
                print('已添加:', out.get('chat_name') or out.get('chat_id'))
                continue
            if choice == '3':
                chat = input('输入 chat / peer_id / username: ').strip()
                if not chat:
                    continue
                dl = input('下载媒体？[y/N]: ').strip().lower() in ('y', 'yes', '1')
                out = await rpc_call(base_args, {'cmd': 'follow.add', 'chat': chat, 'download_media': dl})
                print('已添加:', out.get('chat_name') or out.get('chat_id'))
                continue
            if choice == '4':
                cid = int(input('输入 chat_id: ').strip() or '0')
                enabled = input('开启下载？[y/N]: ').strip().lower() in ('y', 'yes', '1')
                await rpc_call(base_args, {'cmd': 'follow.download', 'chat_id': cid, 'enabled': enabled})
                print('已更新下载开关。')
                continue
            if choice == '5':
                cid = int(input('输入要移除的 chat_id: ').strip() or '0')
                await rpc_call(base_args, {'cmd': 'follow.remove', 'chat_id': cid})
                print('已移除。')
                continue
            if choice == '6':
                cid = int(input('输入 chat_id（0 表示全部）: ').strip() or '0')
                limit = int(input('限制条数 [1000]: ').strip() or '1000')
                out = await rpc_call(base_args, {'cmd': 'backfill-media', 'chat_id': cid, 'limit': limit})
                print('已补入下载队列:', out.get('count', 0))
                continue
            if choice == '0':
                return 0
        except Exception as exc:
            print('错误：' + str(exc))
        print('无效选择，请重试。')


async def interactive_cli_menu(args=None) -> int:
    base_args = args or argparse.Namespace(host='', port=0)
    while True:
        print('\n=== CLI 菜单 ===')
        print('1. Ping server')
        print('2. 查看账号')
        print('3. 查看状态')
        print('4. 查看缓存会话')
        print('5. 频道 / Follow 管理')
        print('6. 手动同步某个 chat')
        print('7. 停止 server')
        print('8. 查看日志路径')
        print('0. 返回')
        choice = input('请选择: ').strip()
        try:
            if choice == '1':
                data = await rpc_call(base_args, {'cmd': 'ping'})
                print(data.get('message') or 'pong')
                continue
            if choice == '2':
                data = await rpc_call(base_args, {'cmd': 'whoami'})
                print(json.dumps(data, ensure_ascii=False, indent=2))
                continue
            if choice == '3':
                data = await rpc_call(base_args, {'cmd': 'status', 'chat_id': 0})
                _print_status(data)
                continue
            if choice == '4':
                data = await rpc_call(base_args, {'cmd': 'dialogs.cached', 'limit': 200})
                rows = data.get('dialogs') or []
                for i, row in enumerate(rows, 1):
                    print(f'{i:>3}. {format_dialog_label(row)}  peer_id={row.get("peer_id") or "-"}  username={row.get("username") or "-"}  type={row.get("entity_type") or "-"}')
                if not rows:
                    print('当前没有缓存会话，请先使用 tg-server login 或 tg-server 菜单刷新。')
                continue
            if choice == '5':
                await interactive_cli_channels(base_args)
                continue
            if choice == '6':
                chat = input('输入 chat / peer_id / username: ').strip()
                if not chat:
                    continue
                dl = input('为媒体创建下载任务？[y/N]: ').strip().lower() in ('y', 'yes', '1')
                out = await rpc_call(base_args, {'cmd': 'sync', 'chat': chat, 'download_media': dl})
                print('同步完成:', out.get('chat_name') or out.get('chat_id'), '新增', out.get('total', 0))
                continue
            if choice == '7':
                await rpc_call(base_args, {'cmd': 'stop'})
                print('已发送 stop 命令。')
                continue
            if choice == '8':
                print_paths()
                continue
            if choice == '0':
                return 0
        except Exception as exc:
            print('错误：' + str(exc))
        print('无效选择，请重试。')


async def cmd_cli(args) -> int:
    if not getattr(args, 'command', None) or args.command == 'menu':
        return await interactive_cli_menu(args)
    if args.command == 'channels':
        return await interactive_cli_channels(args)
    if args.command == 'ping':
        data = await rpc_call(args, {'cmd': 'ping'})
        print(data.get('message') or 'pong')
        return 0
    if args.command == 'whoami':
        data = await rpc_call(args, {'cmd': 'whoami'})
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'dialogs':
        data = await rpc_call(args, {'cmd': 'dialogs', 'limit': args.limit})
        for idx, item in enumerate(data.get('dialogs') or [], 1):
            dtype = 'channel' if item.get('is_channel') else ('group' if item.get('is_group') else ('user' if item.get('is_user') else '-'))
            print(f'{idx:>3}. {item.get("name") or "-"}  peer_id={item.get("peer_id") or "-"}  username={item.get("username") or "-"}  type={dtype}')
        return 0
    if args.command == 'dialogs-cached':
        data = await rpc_call(args, {'cmd': 'dialogs.cached', 'limit': args.limit})
        for idx, item in enumerate(data.get('dialogs') or [], 1):
            print(f'{idx:>3}. {format_dialog_label(item)}  peer_id={item.get("peer_id") or "-"}  username={item.get("username") or "-"}  type={item.get("entity_type") or "-"}')
        return 0
    if args.command == 'sync':
        data = await rpc_call(args, {
            'cmd': 'sync', 'chat': args.chat, 'limit': args.limit, 'no_resume': args.no_resume,
            'after_id': args.after_id, 'newest_first': args.newest_first, 'download_media': args.download_media,
        })
        print('同步完成:', data.get('chat_name') or data.get('chat_id'))
        print('chat_id :', data.get('chat_id'))
        print('peer_id :', data.get('peer_id'))
        print('新增条数:', data.get('total', 0))
        return 0
    if args.command == 'follow':
        if args.follow_cmd == 'add':
            data = await rpc_call(args, {'cmd': 'follow.add', 'chat': args.chat, 'download_media': args.download_media})
            print('已添加:', data.get('chat_name') or data.get('chat_id'))
            return 0
        if args.follow_cmd == 'list':
            data = await rpc_call(args, {'cmd': 'follow.list'})
            print_follow_rows(data.get('follows') or [], verbose=args.verbose)
            return 0
        if args.follow_cmd == 'remove':
            await rpc_call(args, {'cmd': 'follow.remove', 'chat_id': args.chat_id})
            print('已移除。')
            return 0
        if args.follow_cmd == 'enable':
            await rpc_call(args, {'cmd': 'follow.enable', 'chat_id': args.chat_id})
            print('已启用。')
            return 0
        if args.follow_cmd == 'disable':
            await rpc_call(args, {'cmd': 'follow.disable', 'chat_id': args.chat_id})
            print('已禁用。')
            return 0
        if args.follow_cmd == 'download':
            await rpc_call(args, {'cmd': 'follow.download', 'chat_id': args.chat_id, 'enabled': args.enabled == 'true'})
            print('已更新下载开关。')
            return 0
    if args.command == 'backfill-media':
        data = await rpc_call(args, {'cmd': 'backfill-media', 'chat_id': args.chat_id, 'limit': args.limit})
        print('已补入下载队列:', data.get('count', 0))
        return 0
    if args.command == 'status':
        data = await rpc_call(args, {'cmd': 'status', 'chat_id': args.chat_id})
        _print_status(data)
        return 0
    if args.command == 'stop':
        data = await rpc_call(args, {'cmd': 'stop'})
        print(data.get('message') or 'server stopping')
        return 0
    if args.command == 'logs':
        if not LOG_FILE.exists():
            print('日志文件不存在。')
            return 0
        lines = LOG_FILE.read_text(encoding='utf-8', errors='ignore').splitlines()
        tail = max(1, int(args.tail or 100))
        for line in lines[-tail:]:
            print(line)
        return 0
    if args.command == 'paths':
        print_paths()
        return 0
    raise RuntimeError('unknown cli command')


def run_parsed_args(args) -> int:
    try:
        return asyncio.run(cmd_cli(args))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print('\ncli 已取消')
        return 0
    except Exception as exc:
        logger.exception('执行失败')
        print('错误:', friendly_error_message(exc, action='执行命令'))
        return 1


def cli_entry(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_parsed_args(args)


def main(argv: list[str] | None = None) -> int:
    return cli_entry(argv)
