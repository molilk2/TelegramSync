from __future__ import annotations

from getpass import getpass
from typing import Any

from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError

from app.config.config import load_config, save_config
from app.config.paths import SESSION_FILE
from app.core.session import SessionManager
from app.server_helpers import extract_dialog_name, extract_username


def interactive_server_setup(*, api_id: int = 0, api_hash: str = '', host: str = '', port: int = 0):
    cfg = load_config()
    tg = cfg.setdefault('telegram', {})
    rpc = cfg.setdefault('rpc', {})

    current_api_id = str(api_id or tg.get('api_id') or '').strip()
    current_api_hash = str(api_hash or tg.get('api_hash') or '').strip()
    current_host = str(host or rpc.get('host') or '127.0.0.1').strip()
    current_port = str(port or rpc.get('port') or 6389).strip()
    current_token = str(rpc.get('token') or '').strip()

    val = input(f'请输入 Telegram api_id [{current_api_id}]: ').strip()
    tg['api_id'] = int(val or current_api_id or 0)

    masked_hash = ('*' * min(len(current_api_hash), 8)) if current_api_hash else ''
    val = input(f'请输入 Telegram api_hash [{masked_hash}]: ').strip()
    tg['api_hash'] = val or current_api_hash

    val = input(f'请输入本地 RPC host [{current_host}]: ').strip()
    rpc['host'] = val or current_host

    val = input(f'请输入本地 RPC port [{current_port}]: ').strip()
    rpc['port'] = int(val or current_port or 6389)

    token_hint = current_token[:8] + '...' if current_token else '自动生成'
    val = input(f'请输入 RPC token（留空沿用/自动生成）[{token_hint}]: ').strip()
    rpc['token'] = val or current_token or __import__('secrets').token_hex(16)

    save_config(cfg)
    return cfg


def config_is_initialized() -> bool:
    cfg = load_config()
    tg = cfg.get('telegram', {})
    return bool(str(tg.get('api_id') or '').strip() and str(tg.get('api_hash') or '').strip())


async def cache_account_dialogs(client, repo, logger, *, limit: int = 0) -> int:
    count = 0
    rows: list[dict[str, Any]] = []
    async for dialog in client.iter_dialogs(limit=None if int(limit or 0) <= 0 else int(limit)):
        entity = dialog.entity
        chat_id = int(getattr(entity, 'id', 0) or 0)
        try:
            from telethon import utils
            peer_id = utils.get_peer_id(entity)
        except Exception:
            peer_id = chat_id
        entity_type = 'channel' if dialog.is_channel else ('group' if dialog.is_group else 'user')
        rows.append({
            'chat_id': chat_id,
            'peer_id': peer_id,
            'chat_name': extract_dialog_name(dialog, entity),
            'username': extract_username(entity),
            'entity_type': entity_type,
        })
        count += 1
    await repo.replace_dialog_cache(rows)
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
