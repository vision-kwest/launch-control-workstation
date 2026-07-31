"""Small, dependency-free console reporter."""

from __future__ import annotations

import sys


def _write(label: str, message: str, *, error: bool = False) -> None:
    """Emit one immediately flushed, consistently formatted status line.

    Informational output goes to stdout, while warnings and errors go to stderr
    so shell pipelines can separate normal progress from actionable messages.
    Centering the label in a fixed-width field keeps mixed status lines aligned;
    flushing makes long-running provisioning progress visible without buffering.
    """
    print(f"[{label:^5}] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def info(message: str) -> None:
    """Write a normal progress message to stdout with the ``INFO`` label.

    This thin wrapper deliberately centralizes the label choice while leaving
    stream selection, alignment, and flushing to :func:`_write`.
    """
    _write("INFO", message)


def ok(message: str) -> None:
    """Write a successful-step message to stdout with the ``SUCCESS`` label.

    Success is normal program output rather than diagnostic output, so this does
    not set the helper's ``error`` flag and remains visible in captured stdout.
    """
    _write("SUCCESS", message)


def warn(message: str) -> None:
    """Write a non-fatal warning to stderr with the ``WARNING`` label.

    Passing ``error=True`` selects stderr even though execution may continue,
    ensuring warnings are not confused with ordinary machine-consumable output.
    """
    _write("WARNING", message, error=True)


def error(message: str) -> None:
    """Write a fatal or operation-ending message to stderr as ``ERROR``.

    The caller remains responsible for choosing or returning an exit status;
    this function only provides consistent presentation and stream routing.
    """
    _write("ERROR", message, error=True)
