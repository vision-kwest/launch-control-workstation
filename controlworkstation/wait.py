"""Wait helpers."""

from __future__ import annotations

import socket
import time


def ssh(host: str, timeout: int, *, interval: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, 22), timeout=min(interval, 5.0)):
                return
        except OSError as exc:
            last_error = str(exc)
            time.sleep(interval)
    raise TimeoutError(f"SSH on {host}:22 did not become available within {timeout}s ({last_error})")
