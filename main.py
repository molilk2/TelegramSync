from __future__ import annotations

import sys

from app.cli import cli_entry
from app.server import server_entry


def print_usage() -> int:
    print('这是兼容入口，推荐直接使用以下命令：')
    print('  python server_main.py ...')
    print('  python cli_main.py ...')
    print('或：')
    print('  python main.py server ...')
    print('  python main.py cli ...')
    return 2


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return print_usage()
    if argv[0] == 'server':
        return server_entry(argv[1:])
    if argv[0] == 'cli':
        return cli_entry(argv[1:])
    return print_usage()


if __name__ == '__main__':
    raise SystemExit(main())
