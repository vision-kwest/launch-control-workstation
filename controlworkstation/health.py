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
        """Return true only when every requested check completed without error.

        Individual output fields remain available for display even after failures;
        the consolidated error tuple is the authoritative overall health signal.
        """
        return not self.errors


def authenticate(host: str, config: Config) -> None:
    """Prove the configured private key can execute commands as ``ubuntu``.

    A literal ``READY`` response distinguishes successful authentication from mere
    TCP reachability or an unexpected login shell.  Failure details from SSH are
    included in a ``RuntimeError`` with key/fingerprint remediation guidance.
    """
    result = run(host, config, "echo READY", timeout=config.health_check_timeout)
    if result.returncode or result.stdout.strip() != "READY":
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"SSH authentication failed for ubuntu@{host}: {detail}. Verify the private key and EC2 key-pair fingerprint.")


def wait_for_cloud_init(host: str, config: Config, *, interval: float = 10) -> str:
    """Poll cloud-init to completion through temporary disconnects and reboots.

    Each poll uses the shared authenticated SSH path.  Local command timeouts are
    treated as transient because cloud-init may reboot the host; explicit cloud-init
    error/degraded states fail immediately.  A monotonic overall deadline bounds the
    loop and reports the last observation when completion never arrives.
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
    """Run the complete, reusable remote workstation health-check suite.

    Commands verify login, cloud-init, required tool versions, and the timestamp
    marker written at the very end of bootstrap.  All checks run even if one fails,
    producing a concise aggregate rather than forcing operators through one error at
    a time.  Successful stdout is retained verbatim for launch/status presentation.
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
