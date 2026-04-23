from __future__ import annotations

import sys

from app.cli import main as cli_main
from app.server import server_entry


def interactive_launcher() -> int:
    while True:
        print('\n=== tg-daemon-cli ===')
        print('1. Server 菜单')
        print('2. CLI 菜单')
        print('0. 退出')
        choice = input('请选择: ').strip()
        if choice == '1':
            return server_entry([])
        if choice == '2':
            return cli_main([])
        if choice == '0':
            return 0
        print('无效选择，请重试。')


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return interactive_launcher()
    if argv[0] == 'server':
        return server_entry(argv[1:])
    if argv[0] == 'cli':
        return cli_main(argv)
    return cli_main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
