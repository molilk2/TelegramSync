from __future__ import annotations

from telethon import utils as telethon_utils
from telethon.tl.types import DocumentAttributeFilename


def get_chat_name(chat) -> str:
    return getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or getattr(chat, 'username', None) or str(getattr(chat, 'id', ''))


def get_sender_name(sender) -> str:
    if sender is None:
        return ''
    return (
        getattr(sender, 'title', None)
        or ' '.join([p for p in [getattr(sender, 'first_name', None), getattr(sender, 'last_name', None)] if p])
        or getattr(sender, 'username', None)
        or str(getattr(sender, 'id', ''))
    )


def detect_media_kind(msg) -> str:
    if getattr(msg, 'photo', None):
        return 'photo'
    if getattr(msg, 'voice', None):
        return 'voice'
    if getattr(msg, 'video', None):
        return 'video'
    if getattr(msg, 'video_note', None):
        return 'video_note'
    if getattr(msg, 'sticker', None):
        return 'sticker'
    if getattr(msg, 'gif', None):
        return 'gif'
    if getattr(msg, 'audio', None):
        return 'audio'
    if getattr(msg, 'document', None):
        return 'document'
    return ''


def extract_file_name(msg) -> str:
    file_obj = getattr(msg, 'file', None)
    if file_obj and getattr(file_obj, 'name', None):
        return file_obj.name
    media = getattr(msg, 'media', None)
    document = getattr(media, 'document', None)
    if document and getattr(document, 'attributes', None):
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name or ''
    return ''


def _peer_id(entity):
    if entity is None:
        return None
    try:
        return telethon_utils.get_peer_id(entity)
    except Exception:
        return getattr(entity, 'id', None)


def build_compact_raw(chat, msg, sender, file_name: str, media_kind: str) -> dict:
    file_obj = getattr(msg, 'file', None)
    return {
        'chat_id': getattr(chat, 'id', None),
        'chat_peer_id': _peer_id(chat),
        'message_id': getattr(msg, 'id', None),
        'sender_id': getattr(msg, 'sender_id', None),
        'sender_peer_id': _peer_id(sender),
        'date': msg.date.isoformat() if getattr(msg, 'date', None) else '',
        'edit_date': msg.edit_date.isoformat() if getattr(msg, 'edit_date', None) else '',
        'text_preview': (getattr(msg, 'message', '') or '')[:500],
        'reply_to_msg_id': getattr(getattr(msg, 'reply_to', None), 'reply_to_msg_id', None),
        'grouped_id': getattr(msg, 'grouped_id', None),
        'post': bool(getattr(msg, 'post', False)),
        'out': bool(getattr(msg, 'out', False)),
        'mentioned': bool(getattr(msg, 'mentioned', False)),
        'silent': bool(getattr(msg, 'silent', False)),
        'media_kind': media_kind,
        'file_name': file_name,
        'file_ext': getattr(file_obj, 'ext', None) if file_obj else '',
        'mime_type': getattr(file_obj, 'mime_type', None) if file_obj else '',
        'file_size': getattr(file_obj, 'size', None) if file_obj else None,
        'has_media': bool(getattr(msg, 'media', None)),
    }


def normalize_message(chat, msg, sender=None) -> dict:
    file_obj = getattr(msg, 'file', None)
    file_name = extract_file_name(msg)
    media_kind = detect_media_kind(msg)
    compact_raw = build_compact_raw(chat, msg, sender, file_name, media_kind)
    return {
        'chat_id': getattr(chat, 'id', 0),
        'message_id': getattr(msg, 'id', 0),
        'sender_id': getattr(msg, 'sender_id', None),
        'chat_name': get_chat_name(chat),
        'sender_name': get_sender_name(sender),
        'date': msg.date.isoformat() if getattr(msg, 'date', None) else '',
        'text': getattr(msg, 'message', '') or '',
        'raw': compact_raw,
        'media_kind': media_kind,
        'file_name': file_name,
        'file_ext': getattr(file_obj, 'ext', None) if file_obj else '',
        'mime_type': getattr(file_obj, 'mime_type', None) if file_obj else '',
        'file_size': getattr(file_obj, 'size', None) if file_obj else None,
        'grouped_id': getattr(msg, 'grouped_id', None),
    }
