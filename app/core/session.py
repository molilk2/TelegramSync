from __future__ import annotations

from telethon import TelegramClient

try:
    from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
except Exception:  # pragma: no cover
    ConnectionTcpAbridged = None

from app.config.config import load_config
from app.config.paths import SESSION_FILE


class SessionManager:
    def __init__(self):
        self.client = None

    def get_telegram_config(self) -> dict:
        cfg = load_config() or {}
        return cfg.get('telegram', {}) or {}

    def has_credentials(self) -> bool:
        tg = self.get_telegram_config()
        return bool(tg.get('api_id')) and bool(tg.get('api_hash'))

    def build_client(self):
        if self.client is not None:
            return self.client

        tg = self.get_telegram_config()
        api_id = tg.get('api_id')
        api_hash = tg.get('api_hash')
        if not api_id or not api_hash:
            raise RuntimeError('Telegram API ID / API Hash 尚未配置，请先执行 init 命令。')

        kwargs = {
            'auto_reconnect': bool(tg.get('auto_reconnect', True)),
            'sequential_updates': bool(tg.get('sequential_updates', True)),
            'receive_updates': bool(tg.get('receive_updates', True)),
            'request_retries': int(tg.get('request_retries', 8) or 8),
            'connection_retries': int(tg.get('connection_retries', 8) or 8),
            'retry_delay': int(tg.get('retry_delay', 2) or 2),
            'timeout': int(tg.get('timeout', 20) or 20),
        }
        if ConnectionTcpAbridged is not None:
            kwargs['connection'] = ConnectionTcpAbridged

        self.client = TelegramClient(
            str(SESSION_FILE),
            int(api_id),
            str(api_hash),
            **kwargs,
        )
        return self.client

    async def disconnect_client(self):
        if self.client is None:
            return
        try:
            if self.client.is_connected():
                await self.client.disconnect()
        finally:
            self.client = None
