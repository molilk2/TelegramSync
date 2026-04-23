from __future__ import annotations


def friendly_error_message(exc: Exception | str, action: str = '操作') -> str:
    text = str(exc).strip() if not isinstance(exc, str) else exc.strip()
    low = text.lower()

    if 'cannot find any entity corresponding to' in low:
        return (
            '找不到这个会话。\n'
            '可能原因：\n'
            '1. 当前登录账号看不到这个频道/群/用户\n'
            '2. 传入的 chat id、peer_id 或 username 不正确\n'
            '3. server 还没有解析到这个实体\n\n'
            '建议先执行：python main.py cli dialogs --limit 200\n'
            '再从结果里复制真实的 peer_id 或 username 重试。'
        )

    if 'separator is found, but chunk is longer than limit' in low:
        return 'server 返回的数据过大，当前客户端无法完整读取。请更新 server 和 cli 到同一版本后重试。'

    if 'connection refused' in low or 'connect call failed' in low:
        return '无法连接到本地 server。请先执行 `python main.py server run`。'

    if 'server closed connection' in low:
        return 'server 提前关闭了连接。请检查 server 日志后重试。'

    if 'database is locked' in low:
        return '数据库当前正忙，请稍后再试。'

    if 'floodwait' in low or 'flood wait' in low:
        return f'{action}过于频繁，被 Telegram 临时限流。请稍后再试。'

    if 'timed out' in low or 'timeout' in low:
        return f'{action}超时。请检查网络或稍后再试。'

    if 'not authorized' in low or 'authorization' in low:
        return '当前 server 尚未完成登录。请先执行 `python main.py server login`。'

    if text.startswith('unknown cmd:'):
        cmd = text.split(':', 1)[1].strip()
        return f'不支持的 server 命令：{cmd}'

    if text.startswith('missing cmd'):
        return '请求缺少命令字段。'

    return f'{action}失败：{text}' if text else f'{action}失败。'


def format_command_usage_error(message: str) -> str:
    msg = (message or '').strip()
    if "invalid choice: 'mirror'" in msg:
        return (
            '不支持的一级命令：mirror\n\n'
            '当前可用命令：init、server、cli、logs、paths\n'
            '旧版 mirror 命令已经移除。\n'
            '请改用：\n'
            '  python main.py server run\n'
            '  python main.py cli follow add --chat ...\n'
            '  python main.py cli sync --chat ...'
        )
    if 'invalid choice' in msg:
        return '命令或参数不正确。请执行 `python main.py -h` 查看帮助。'
    if 'the following arguments are required' in msg:
        return '缺少必填参数。请执行 `python main.py -h` 或对应子命令的 `-h` 查看帮助。'
    return msg or '命令行参数不正确。'
