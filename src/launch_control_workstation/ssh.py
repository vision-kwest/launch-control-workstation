"""SSH client helpers."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from .config import Config
from .process import call
from .process import run as run_process


def command(host: str, config: Config, extra: Sequence[str] = ()) -> list[str]:
    """Construct the shared SSH argument vector for a workstation connection.

    The private-key path is derived by removing the public key's ``.pub`` suffix,
    matching key creation in the AWS helper.  ``IdentitiesOnly`` prevents an SSH
    agent's unrelated keys from exhausting the server's authentication attempts.
    Caller-supplied SSH options precede the destination, making this builder
    usable for both interactive and batch connections.
    """
    return ["ssh", "-i", str(config.public_key.with_suffix("")),
            "-o", "IdentitiesOnly=yes", *extra, f"ubuntu@{host}"]


def run(host: str, config: Config, remote_command: str, *,
        timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run one bounded, non-interactive command with the interactive login key.

    Batch mode prevents password prompts, new host keys are accepted on first
    contact, and SSH's connection establishment is independently limited to ten
    seconds.  Output and exit status are returned without raising for a remote
    nonzero status because health checks need both streams for diagnostics.

    Raises:
        TimeoutError: If the overall subprocess exceeds ``timeout``; the native
            subprocess exception is translated for a simpler public API.
    """
    options = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ConnectTimeout=10")
    return run_process([*command(host, config, options), remote_command], timeout=timeout)


def connect(host: str, config: Config) -> int:
    """Hand control to an interactive SSH client and return its process status.

    Unlike :func:`run`, this inherits the terminal and standard streams so the
    user receives a normal interactive session.  Returning rather than raising
    on the SSH exit code lets command-line entry points propagate it directly.
    """
    return call(command(host, config))
