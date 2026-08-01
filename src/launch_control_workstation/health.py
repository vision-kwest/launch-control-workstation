"""Single source of truth for local and remote workstation health."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from .aws import Instance, aws
from .config import Config
from .ssh import run


@dataclass(frozen=True)
class Check:
    """One named health observation."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class HealthReport:
    """Complete infrastructure, connectivity, provisioning, tool, and system state."""

    infrastructure: tuple[Check, ...] = ()
    connectivity: tuple[Check, ...] = ()
    provisioning: tuple[Check, ...] = ()
    tools: tuple[Check, ...] = ()
    aws_authentication: tuple[Check, ...] = ()
    system: tuple[Check, ...] = ()

    @property
    def checks(self) -> tuple[Check, ...]:
        return self.infrastructure + self.connectivity + self.provisioning + self.tools + self.aws_authentication + self.system

    @property
    def healthy(self) -> bool:
        return bool(self.checks) and all(item.passed for item in self.checks)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(f"{item.name}: {item.detail}" for item in self.checks if not item.passed)


def injected_key_health(instance: Instance, config: Config) -> Check:
    """Verify EC2 records the exact key-pair name validated by the launcher."""
    return Check("SSH key injected", instance.key_name == config.key_name,
                 instance.key_name or "no EC2 key pair recorded")


def instance_health(instance: Instance, config: Config) -> tuple[Check, ...]:
    """Check existence, state, EC2 status, and injected SSH key identity."""
    exists = bool(instance.instance_id)
    running = instance.state == "running"
    status_ok = False
    detail = "not available while instance is not running"
    if exists and running:
        data = aws(["ec2", "describe-instance-status", "--instance-ids", instance.instance_id,
                    "--include-all-instances"], config)
        statuses = data.get("InstanceStatuses", [])
        if statuses:
            system = statuses[0].get("SystemStatus", {}).get("Status", "unknown")
            guest = statuses[0].get("InstanceStatus", {}).get("Status", "unknown")
            status_ok = system == guest == "ok"
            detail = f"system={system}, instance={guest}"
        else:
            detail = "EC2 has not reported status checks"
    return (Check("Instance exists", exists, instance.instance_id or "not found"),
            Check("Instance running", running, instance.state or "unknown"),
            Check("Status checks", status_ok, detail),
            injected_key_health(instance, config))


def port_reachable(host: str, *, timeout: float = 5) -> Check:
    """Test whether TCP port 22 can be reached."""
    try:
        with socket.create_connection((host, 22), timeout=timeout):
            return Check("SSH port", True, "reachable")
    except OSError as exc:
        return Check("SSH port", False, str(exc))


def authenticate(host: str, config: Config) -> Check:
    """Prove the configured private key can execute a remote command."""
    result = run(host, config, "printf AUTHENTICATED", timeout=config.health_check_timeout)
    passed = result.returncode == 0 and result.stdout == "AUTHENTICATED"
    detail = "authenticated" if passed else (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
    return Check("SSH authentication", passed, detail)


def _remote(host: str, config: Config, name: str, command: str) -> Check:
    try:
        result = run(host, config, command, timeout=config.health_check_timeout)
    except TimeoutError as exc:
        return Check(name, False, str(exc))
    detail = (result.stdout or result.stderr).strip()
    return Check(name, result.returncode == 0 and bool(detail), detail or f"exit {result.returncode}")


def remote_health(host: str, config: Config) -> HealthReport:
    """Run every connectivity, provisioning, toolchain, and system probe."""
    port = port_reachable(host)
    try:
        auth = authenticate(host, config) if port.passed else Check("SSH authentication", False, "port unavailable")
    except TimeoutError as exc:
        auth = Check("SSH authentication", False, str(exc))
    if not auth.passed:
        return HealthReport(connectivity=(port, auth))
    cloud = _remote(host, config, "cloud-init", "cloud-init status")
    cloud = Check(cloud.name, cloud.passed and "status: done" in cloud.detail, cloud.detail)
    bootstrap = _remote(host, config, "bootstrap", "cat /var/lib/launch-control-workstation/bootstrap-completed")
    tools = tuple(_remote(host, config, name, command) for name, command in (
        ("OpenTofu", "tofu version | head -n1"), ("Git", "git --version"),
        ("GitHub CLI", "gh --version | head -n1"), ("Python", "python3 --version")))
    profile = _remote(host, config, "Instance Profile attached", "t=$(curl -fsS --max-time 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token) && curl -fsS --max-time 2 -H \"X-aws-ec2-metadata-token: $t\" http://169.254.169.254/latest/meta-data/iam/info | grep -q InstanceProfileArn && echo attached")
    imds = _remote(host, config, "IMDS available", "t=$(curl -fsS --max-time 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token) && curl -fsS --max-time 2 -H \"X-aws-ec2-metadata-token: $t\" http://169.254.169.254/latest/meta-data/iam/security-credentials/ | head -n1")
    credentials = _remote(host, config, "Temporary credentials", "aws configure list 2>/dev/null | grep -q 'iam-role' && echo 'IMDS role credentials'")
    sts = _remote(host, config, "STS authentication", "env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_PROFILE AWS_SHARED_CREDENTIALS_FILE=/dev/null aws sts get-caller-identity --output json")
    system = tuple(_remote(host, config, name, command) for name, command in (
        ("Uptime", "uptime -p"),
        ("Reboot pending", "if [ -e /var/run/reboot-required ]; then echo pending; exit 1; else echo not pending; fi"),
        ("Disk", "p=$(df -P / | awk 'NR==2 {gsub(/%/,\"\",$5); print $5}'); echo \"${p}% used\"; [ \"$p\" -lt 90 ]"),
        ("Memory", "a=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo); echo \"${a} MiB available\"; [ \"$a\" -ge 256 ]")))
    return HealthReport(connectivity=(port, auth), provisioning=(cloud, bootstrap), tools=tools,
                        aws_authentication=(profile, imds, credentials, sts), system=system)


def check(instance: Instance, config: Config) -> HealthReport:
    """Return the complete health report for one managed instance."""
    infra = instance_health(instance, config)
    if instance.state != "running" or not instance.public_ip:
        return HealthReport(infrastructure=infra,
                            connectivity=(Check("SSH port", False, "instance has no reachable public address"),))
    remote = remote_health(instance.public_ip, config)
    return HealthReport(infrastructure=infra, connectivity=remote.connectivity,
                        provisioning=remote.provisioning, tools=remote.tools,
                        aws_authentication=remote.aws_authentication, system=remote.system)


def wait_for_cloud_init(host: str, config: Config, *, interval: float = 10) -> str:
    """Wait through transient disconnects and automatic reboots until cloud-init is done."""
    deadline = time.monotonic() + config.cloud_init_timeout
    last = "unreachable"
    while time.monotonic() < deadline:
        try:
            probe = _remote(host, config, "cloud-init", "cloud-init status 2>&1")
            last = probe.detail
            if probe.passed and "status: done" in last:
                return last
            if "status: error" in last or "status: degraded" in last:
                raise RuntimeError(f"cloud-init failed: {last}")
        except TimeoutError:
            last = "SSH unavailable (the machine may be rebooting)"
        time.sleep(interval)
    raise TimeoutError(f"cloud-init did not complete within {config.cloud_init_timeout}s (last: {last})")


def wait_until_healthy(instance: Instance, config: Config, *, interval: float = 10) -> HealthReport:
    """Wait for a post-cloud-init reboot and require every health check to pass."""
    deadline = time.monotonic() + config.cloud_init_timeout
    last = HealthReport()
    while time.monotonic() < deadline:
        try:
            last = check(instance, config)
            if last.healthy:
                return last
        except (TimeoutError, OSError):
            pass
        time.sleep(interval)
    raise TimeoutError("workstation did not become healthy: " + "; ".join(last.errors))
