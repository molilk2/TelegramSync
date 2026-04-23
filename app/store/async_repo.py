from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable


class AsyncRepo:
    """Small async facade around the synchronous Repo.

    SQLite stays in the existing Repo, but daemon-facing code calls through this
    wrapper so file I/O and commits do not block the asyncio event loop.
    """

    def __init__(self, sync_repo):
        self.sync_repo = sync_repo

    async def call(self, func: Callable[..., Any] | str, /, *args, **kwargs):
        if isinstance(func, str):
            target = getattr(self.sync_repo, func)
        else:
            target = func
        return await asyncio.to_thread(partial(target, *args, **kwargs))

    def __getattr__(self, name: str):
        target = getattr(self.sync_repo, name)
        if not callable(target):
            return target

        async def _wrapper(*args, **kwargs):
            return await asyncio.to_thread(partial(target, *args, **kwargs))

        return _wrapper
