from __future__ import annotations

import contextlib
import os
from typing import Any

from app.config.paths import DATA_DIR
from app.utils import now_ts

SERVER_LOCK_FILE = DATA_DIR / 'server.lock'


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


class ServerInstanceLock:
    def __init__(self, *, host: str, port: int):
        self.host = host
        self.port = port
        self.path = SERVER_LOCK_FILE
        self.fd: int | None = None
        self.acquired = False

    def _read_info(self) -> dict[str, Any]:
        try:
            import json
            return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def acquire(self) -> None:
        import json

        payload = {
            'pid': os.getpid(),
            'host': self.host,
            'port': self.port,
            'started_at': now_ts(),
        }

        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
                os.fsync(fd)
                self.fd = fd
                self.acquired = True
                return
            except FileExistsError:
                info = self._read_info()
                pid = int(info.get('pid') or 0)
                if pid and pid_exists(pid):
                    raise RuntimeError(
                        f'server 已在运行（pid={pid}, {info.get("host") or "127.0.0.1"}:{info.get("port") or "?"}）。'
                        '请先使用 cli stop，或结束现有 server 进程。'
                    )
                with contextlib.suppress(FileNotFoundError):
                    self.path.unlink()
                continue

    def release(self) -> None:
        if self.fd is not None:
            with contextlib.suppress(Exception):
                os.close(self.fd)
            self.fd = None
        if self.acquired:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            self.acquired = False
