from __future__ import annotations

import json
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
        },
        'mirror': {
            'download_media': False,
            'download_root': '',
            'organize_by_chat': True,
            'filename_mode': 'message_id',
            'overwrite': False,
        },
        'rpc': {
            'host': '127.0.0.1',
            'port': 6389,
        },
    }


def load_config() -> dict[str, Any]:
    base = default_config()
    if not CONFIG_FILE.exists():
        return base
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        raw = json.load(f) or {}
    for key in ('telegram', 'mirror'):
        if isinstance(raw.get(key), dict):
            base[key].update(raw[key])
    for key, value in raw.items():
        if key not in base:
            base[key] = value
    return base


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
