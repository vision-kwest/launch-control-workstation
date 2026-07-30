"""Small, dependency-free console reporter."""

from __future__ import annotations

import sys


def _write(label: str, message: str, *, error: bool = False) -> None:
    print(f"[{label:^5}] {message}", file=sys.stderr if error else sys.stdout, flush=True)


def info(message: str) -> None:
    _write("INFO", message)


def ok(message: str) -> None:
    _write("OK", message)


def warn(message: str) -> None:
    _write("WARN", message, error=True)


def error(message: str) -> None:
    _write("ERROR", message, error=True)
