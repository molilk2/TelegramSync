from __future__ import annotations

import asyncio
import json
from typing import Any


def encode_message(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def write_message(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    raw = encode_message(payload)
    writer.write(len(raw).to_bytes(4, byteorder="big", signed=False))
    writer.write(raw)
    await writer.drain()


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None
    if not header:
        return None
    size = int.from_bytes(header, byteorder="big", signed=False)
    if size <= 0:
        return {}
    payload = await reader.readexactly(size)
    return json.loads(payload.decode("utf-8"))


async def send_request(host: str, port: int, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        await asyncio.wait_for(write_message(writer, payload), timeout=timeout)
        resp = await asyncio.wait_for(read_message(reader), timeout=timeout)
        if resp is None:
            return {"ok": False, "error": "server closed connection"}
        return resp
    finally:
        writer.close()
        await writer.wait_closed()
