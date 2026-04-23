from __future__ import annotations

import base64
import json
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


def sanitize_name(value: str, fallback: str = 'unknown') -> str:
    value = (value or '').strip()
    if not value:
        return fallback
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')
    return value[:120] or fallback


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
