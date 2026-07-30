"""Compatibility wait helpers backed by the central health framework."""

from __future__ import annotations

import time

from .health import port_reachable


def ssh(host: str, timeout: int, *, interval: float = 5.0) -> None:
    """Wait for SSH transport using the canonical connectivity health check."""
    deadline = time.monotonic() + timeout
    last = "not attempted"
    while time.monotonic() < deadline:
        result = port_reachable(host, timeout=min(interval, 5.0))
        if result.passed:
            return
        last = result.detail
        time.sleep(interval)
    raise TimeoutError(f"SSH on {host}:22 did not become available within {timeout}s ({last})")
