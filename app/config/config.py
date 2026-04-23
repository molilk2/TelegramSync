from __future__ import annotations

import json
import secrets
from typing import Any

from app.config.paths import CONFIG_FILE, CONFIG_DIR


def default_config() -> dict[str, Any]:
    return {
        'telegram': {
            'api_id': '',
            'api_hash': '',
            'auto_reconnect': True,
            'sequential_updates': True,
            'receive_updates': True,
            'request_retries': 8,
            'connection_retries': 8,
            'retry_delay': 2,
            'timeout': 20,
        },
        'mirror': {
            'download_media': False,
            'download_root': '',
            'organize_by_chat': True,
            'filename_mode': 'message_id',
            'overwrite': False,
            'download_max_attempts_per_round': 4,
            'download_job_retry_delay': 180,
            'download_retry_backoff_base': 2,
            'download_retry_backoff_cap': 20,
            'download_worker_count': 2,
            'download_stale_after_seconds': 900,
        },
        'rpc': {
            'host': '127.0.0.1',
            'port': 6389,
            'token': '',
        },
    }


def load_config() -> dict[str, Any]:
    base = default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f) or {}
        except (OSError, json.JSONDecodeError):
            raw = {}
        for key in ('telegram', 'mirror', 'rpc'):
            if isinstance(raw.get(key), dict):
                base[key].update(raw[key])
        for key, value in raw.items():
            if key not in base:
                base[key] = value
    token_changed = False
    if not str(base.get('rpc', {}).get('token') or '').strip():
        base.setdefault('rpc', {})['token'] = secrets.token_hex(16)
        token_changed = True
    if token_changed:
        try:
            save_config(base)
        except OSError:
            pass
    return base


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
