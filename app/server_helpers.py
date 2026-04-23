from __future__ import annotations

from typing import Any

from telethon import utils


def row_has(row, key: str) -> bool:
    try:
        if hasattr(row, 'keys'):
            return key in row.keys()
    except Exception:
        pass
    try:
        row[key]
        return True
    except Exception:
        return False


def row_value(row, key: str, default=None):
    try:
        value = row[key]
    except Exception:
        return default
    return default if value is None else value


def extract_dialog_name(dialog, entity) -> str:
    candidates: list[Any] = [
        getattr(dialog, 'name', None),
        utils.get_display_name(entity) if entity is not None else None,
        getattr(entity, 'title', None),
        ' '.join(
            x for x in [
                getattr(entity, 'first_name', None),
                getattr(entity, 'last_name', None),
            ] if x
        ).strip() or None,
        getattr(entity, 'username', None),
        getattr(entity, 'phone', None),
    ]

    usernames = getattr(entity, 'usernames', None)
    if usernames:
        for item in usernames:
            uname = getattr(item, 'username', None)
            if uname:
                candidates.append(uname)
                break

    eid = getattr(entity, 'id', None)
    if eid not in (None, '', 0, '0'):
        candidates.append(str(eid))

    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ''


def extract_username(entity) -> str:
    uname = getattr(entity, 'username', None)
    if uname:
        return str(uname).strip()

    usernames = getattr(entity, 'usernames', None)
    if usernames:
        for item in usernames:
            value = getattr(item, 'username', None)
            if value:
                text = str(value).strip()
                if text:
                    return text
    return ''
