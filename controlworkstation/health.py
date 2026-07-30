"""Reusable remote workstation health verification."""

from __future__ import annotations

from dataclasses import dataclass
import time

from .config import Config
from .ssh import run


@dataclass(frozen=True)
class HealthReport:
    ssh: str = ""
    cloud_init: str = ""
    tofu: str = ""
    git: str = ""
    gh: str = ""
    python: str = ""
    bootstrap_completed: str = ""
    errors: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        """Report aggregate success; individual output fields remain diagnostic.

        :func:`check` records one error for every failed or empty probe, making
        the absence of errors the single source of truth for overall health.
        """
        return not self.errors


def authenticate(host: str, config: Config) -> None:
    """Prove that SSH key authentication can execute a command on ``host``.

    Merely opening port 22 does not prove that the generated private key matches
    the EC2 key pair.  This probe therefore requires both a zero exit status and
    the exact sentinel ``READY`` before launch proceeds.

    Raises:
        RuntimeError: If SSH fails or returns output other than the sentinel.
        TimeoutError: If the underlying SSH process exceeds the health timeout.
    """
    result = run(host, config, "echo READY", timeout=config.health_check_timeout)
    if result.returncode or result.stdout.strip() != "READY":
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"SSH authentication failed for ubuntu@{host}: {detail}. Verify the private key and EC2 key-pair fingerprint.")


def wait_for_cloud_init(host: str, config: Config, *, interval: float = 10) -> str:
    """Wait for cloud-init, tolerating temporary SSH loss during its reboot.

    Polling uses a monotonic deadline so wall-clock adjustments cannot lengthen
    or shorten the configured timeout.  Command timeouts are considered
    transient because cloud-init may reboot the host; explicit error/degraded
    states fail immediately, while a successful ``status: done`` is returned to
    the caller for diagnostics.

    Raises:
        RuntimeError: If cloud-init reports an error or degraded state.
        TimeoutError: If no completed status arrives before the deadline.
    """
    deadline = time.monotonic() + config.cloud_init_timeout
    last = "unreachable"
    while time.monotonic() < deadline:
        try:
            result = run(host, config, "cloud-init status 2>&1", timeout=config.health_check_timeout)
        except TimeoutError:
            last = "SSH temporarily unreachable (the instance may be rebooting)"
            time.sleep(interval)
            continue
        last = (result.stdout or result.stderr).strip()
        if result.returncode == 0 and "status: done" in last:
            return last
        if "status: error" in last or "status: degraded" in last:
            raise RuntimeError(f"cloud-init failed: {last}")
        time.sleep(interval)
    raise TimeoutError(f"cloud-init did not complete within {config.cloud_init_timeout}s (last result: {last})")


def check(host: str, config: Config) -> HealthReport:
    """Run the complete remote health suite and retain every probe's output.

    Checks are sequential to keep SSH behavior and reported failures easy to
    correlate.  Standard output is preferred, stderr is used as a fallback, and
    empty output or a nonzero status fails any probe.  Cloud-init has the extra
    semantic requirement that its output include ``status: done``.  All probes
    run even after failures so status reporting can present one comprehensive
    :class:`HealthReport` rather than stopping at the first problem.
    """
    checks = {
        "ssh": "echo READY", "cloud_init": "cloud-init status",
        "tofu": "tofu version | head -n1", "git": "git --version",
        "gh": "gh --version | head -n1", "python": "python3 --version",
        "bootstrap_completed": "cat /var/lib/launch-control-workstation/bootstrap-completed",
    }
    values: dict[str, str] = {}
    errors: list[str] = []
    for name, remote_command in checks.items():
        result = run(host, config, remote_command, timeout=config.health_check_timeout)
        value = (result.stdout or result.stderr).strip()
        values[name] = value
        if result.returncode or not value or (name == "cloud_init" and "status: done" not in value):
            errors.append(f"{name.replace('_', ' ')}: {value or f'exit status {result.returncode}'}")
    return HealthReport(**values, errors=tuple(errors))
