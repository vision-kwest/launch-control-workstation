"""Configuration, with environment variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from launch_control_workstation.version import __version__


def _integer(name: str, default: int) -> int:
    """Read an integer setting from the process environment.

    ``default`` is returned only when ``name`` is entirely absent.  A present but
    malformed value is treated as a configuration error rather than silently
    falling back, so operator typos cannot provision unexpectedly sized or
    timed resources.

    Raises:
        ValueError: If the environment value cannot be parsed as a base-10
            integer by :class:`int`.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _boolean(name: str, default: bool) -> bool:
    """Read a deliberately constrained boolean environment setting.

    The common truthy spellings ``1``, ``true``, ``yes``, and ``on`` and their
    false counterparts are accepted case-insensitively.  Returning the supplied
    default for a missing variable preserves the dataclass defaults, while
    rejecting every other present value prevents ambiguous configuration.

    Raises:
        ValueError: If ``name`` is set to an unsupported boolean spelling.
    """
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false, got {value!r}")


@dataclass(frozen=True)
class Config:
    region: str = field(default_factory=lambda: os.getenv("LCW_REGION", "us-east-1"))
    instance_type: str = field(default_factory=lambda: os.getenv("LCW_INSTANCE_TYPE", "t3.large"))
    disk_size: int = field(default_factory=lambda: _integer("LCW_DISK_SIZE", 100))
    owner: str = field(default_factory=lambda: os.getenv("LCW_OWNER", os.getenv("USER", "studio")))
    project: str = field(default_factory=lambda: os.getenv("LCW_PROJECT", "StudioInfrastructure"))
    environment: str = field(default_factory=lambda: os.getenv("LCW_ENVIRONMENT", "development"))
    ssh_timeout: int = field(default_factory=lambda: _integer("LCW_SSH_TIMEOUT", 600))
    cloud_init_timeout: int = field(default_factory=lambda: _integer("LCW_CLOUD_INIT_TIMEOUT", 1800))
    health_check_timeout: int = field(default_factory=lambda: _integer("LCW_HEALTH_CHECK_TIMEOUT", 60))
    auto_login: bool = field(default_factory=lambda: _boolean("LCW_AUTO_LOGIN", False))
    ssh_cidr: str = field(default_factory=lambda: os.getenv("LCW_SSH_CIDR", "0.0.0.0/0"))
    public_key: Path = field(default_factory=lambda: Path(os.getenv("LCW_PUBLIC_KEY", "~/.ssh/id_ed25519.pub")).expanduser())
    key_name: str = field(default_factory=lambda: os.getenv("LCW_KEY_NAME", "launch-control-workstation"))
    bootstrap_key_name: str = field(default_factory=lambda: os.getenv(
        "LCW_BOOTSTRAP_KEY_NAME", "launch-control-workstation-bootstrap"
    ))
    security_group_name: str = field(default_factory=lambda: os.getenv("LCW_SECURITY_GROUP", "launch-control-workstation"))
    version: str = __version__

    @property
    def tags(self) -> dict[str, str]:
        """Build the canonical ownership tags applied to managed AWS resources.

        A new dictionary is produced on every access, allowing callers and the
        AWS serialization layer to manipulate their copy without mutating this
        frozen configuration object.  The fixed ``Role`` and ``ManagedBy`` tags
        are also the identity filters used when discovering existing instances.
        """
        return {
            "Project": self.project,
            "Role": "ControlWorkstation",
            "ManagedBy": "launch-control-workstation",
            "Owner": self.owner,
            "Environment": self.environment,
            "Version": self.version,
        }
