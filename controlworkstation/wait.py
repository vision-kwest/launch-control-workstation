"""Wait helpers."""

from __future__ import annotations

import socket
import time


def ssh(host: str, timeout: int, *, interval: float = 5.0) -> None:
    """Wait until the host accepts a TCP connection on the SSH port.

    This inexpensive network probe is only the availability phase; callers must
    separately authenticate before claiming readiness.  A monotonic deadline is
    immune to wall-clock adjustments, transient socket errors are retried, and the
    final exception includes the last network diagnostic seen by the operator.
    """
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
