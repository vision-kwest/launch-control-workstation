"""Central subprocess execution used by all command adapters."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def run(command: Sequence[str], *, timeout: int | None = None,
        capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    """Execute a command predictably without raising for a non-zero exit."""
    try:
        return subprocess.run(list(command), text=True, capture_output=capture_output,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc


def call(command: Sequence[str]) -> int:
    """Execute an interactive command with inherited standard streams."""
    return subprocess.call(list(command))
