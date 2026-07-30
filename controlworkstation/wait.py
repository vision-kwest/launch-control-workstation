"""Wait helpers."""

from __future__ import annotations

import socket
import time


def ssh(host: str, timeout: int, *, interval: float = 5.0) -> None:
    """Poll until ``host`` accepts a TCP connection on the SSH port.

    This deliberately checks transport availability only; key authentication is
    verified separately after EC2 and sshd are ready.  A monotonic deadline is
    immune to system clock changes, each socket is closed by its context manager,
    and the last operating-system error is retained to make a final timeout
    useful for diagnosing routing, security-group, or boot failures.

    Raises:
        TimeoutError: If port 22 never accepts a connection within ``timeout``.
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
