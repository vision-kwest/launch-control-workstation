"""SSH client helpers."""

from __future__ import annotations

import subprocess
from typing import Sequence

from .config import Config


def command(host: str, config: Config, extra: Sequence[str] = ()) -> list[str]:
    return ["ssh", "-i", str(config.public_key.with_suffix("")),
            "-o", "IdentitiesOnly=yes", *extra, f"ubuntu@{host}"]


def run(host: str, config: Config, remote_command: str, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run one non-interactive command using the exact key used by ``connect``."""
    options = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ConnectTimeout=10", remote_command)
    try:
        return subprocess.run(command(host, config, options), text=True,
                              capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"SSH command timed out after {timeout}s") from exc


def connect(host: str, config: Config) -> int:
    return subprocess.call(command(host, config))
