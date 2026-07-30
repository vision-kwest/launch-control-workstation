"""SSH client helpers."""

from __future__ import annotations

import subprocess
from typing import Sequence

from .config import Config


def command(host: str, config: Config, extra: Sequence[str] = ()) -> list[str]:
    return ["ssh", "-i", str(config.public_key.with_suffix("")), *extra, f"ubuntu@{host}"]


def connect(host: str, config: Config) -> int:
    return subprocess.call(command(host, config))
