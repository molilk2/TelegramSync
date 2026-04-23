from __future__ import annotations

import base64
import json
import os
import re
import time
import zlib
from datetime import date, datetime
from pathlib import Path


def now_ts() -> int:
    return int(time.time())


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except Exception:
            return {'__bytes_b64__': base64.b64encode(obj).decode('ascii')}
    if isinstance(obj, set):
        return list(obj)
    if hasattr(obj, 'to_dict') and callable(obj.to_dict):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, '__dict__'):
        try:
            return obj.__dict__
        except Exception:
            pass
    return str(obj)


def to_json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=_json_default).encode('utf-8')


def dump_json(data) -> str:
    return to_json_bytes(data).decode('utf-8')


def dump_json_compact_compressed(data) -> str:
    raw = to_json_bytes(data)
    compressed = zlib.compress(raw, level=9)
    return 'z:' + base64.b64encode(compressed).decode('ascii')


WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
}


def sanitize_name(value: str, fallback: str = 'unknown', *, max_length: int = 120) -> str:
    value = (value or '').strip()
    if not value:
        value = fallback

    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')
    if not value:
        value = fallback

    stem = Path(value).stem or value
    suffix = Path(value).suffix
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f'_{stem}'
        value = stem + suffix

    if len(value) > max_length:
        if suffix and len(suffix) < max_length:
            stem_max = max_length - len(suffix)
            value = f'{stem[:stem_max]}{suffix}'
        else:
            value = value[:max_length]

    return value or fallback


def limit_path_component_lengths(path: Path, *, max_component_length: int = 120) -> Path:
    parts = []
    for part in path.parts:
        if part in (path.anchor, os.sep, ''):
            parts.append(part)
        else:
            parts.append(sanitize_name(part, fallback='item', max_length=max_component_length))
    return Path(*parts)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
