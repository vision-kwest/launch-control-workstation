"""Small, dependency-free console reporter."""

from __future__ import annotations

import sys


def _write(label: str, message: str, *, error: bool = False) -> None:
    """Emit one immediately flushed, consistently labelled console message.

    Routine progress is written to stdout, while warnings and errors can request
    stderr via ``error``.  Flushing is intentional: CloudShell users must see live
    progress while long-running EC2 and cloud-init waits are in progress.
    """
    print(f"[{label:^5}] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def info(message: str) -> None:
    """Report neutral progress information to standard output."""
    _write("INFO", message)


def ok(message: str) -> None:
    """Report that a meaningful operation or verification succeeded."""
    _write("SUCCESS", message)


def warn(message: str) -> None:
    """Report a recoverable concern to standard error without raising it."""
    _write("WARNING", message, error=True)


def error(message: str) -> None:
    """Report the concise terminal error that caused a command to fail."""
    _write("ERROR", message, error=True)
