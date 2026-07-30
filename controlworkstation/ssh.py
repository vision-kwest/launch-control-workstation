"""SSH client helpers."""

from __future__ import annotations

import subprocess
from typing import Sequence

from .config import Config


def command(host: str, config: Config, extra: Sequence[str] = ()) -> list[str]:
    """Construct the shared SSH argv used by interactive and automated callers.

    The private key is derived from the configured ``.pub`` path, and
    ``IdentitiesOnly`` prevents an agent's unrelated keys from masking a key-pair
    mismatch.  ``extra`` is inserted before the destination for SSH options and,
    optionally, a remote command.  Returning argv avoids unsafe shell expansion.
    """
    return ["ssh", "-i", str(config.public_key.with_suffix("")),
            "-o", "IdentitiesOnly=yes", *extra, f"ubuntu@{host}"]


def run(host: str, config: Config, remote_command: str, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run one non-interactive remote command with the shared SSH identity.

    Batch mode guarantees that health checks never hang waiting for a password or
    host-key prompt.  New host keys are accepted and persisted, command output is
    captured for diagnostics, and non-zero remote exits are returned to the caller
    for contextual handling.  Only a local subprocess timeout is translated into
    ``TimeoutError``; authentication and remote failures remain in the result.
    """
    options = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ConnectTimeout=10", remote_command)
    try:
        return subprocess.run(command(host, config, options), text=True,
                              capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"SSH command timed out after {timeout}s") from exc


def connect(host: str, config: Config) -> int:
    """Replace automated behavior with an interactive user SSH session.

    Unlike ``run``, this call deliberately inherits the terminal's input and
    output.  Its SSH exit status is returned unchanged so launcher and wrapper
    scripts behave like the native client when the session ends.
    """
    return subprocess.call(command(host, config))
