"""Configuration, with environment variable overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _integer(name: str, default: int) -> int:
    """Read one integer setting from the process environment.

    ``default`` is returned only when ``name`` is absent.  An explicitly supplied
    but malformed value is rejected rather than silently falling back, because a
    typo in a timeout or disk size should stop the command before AWS is changed.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _boolean(name: str, default: bool) -> bool:
    """Read a human-friendly boolean setting from the environment.

    Common shell spellings are accepted case-insensitively.  Unknown values raise
    ``ValueError`` so operators can distinguish bad configuration from a false
    setting instead of accidentally enabling or disabling automatic login.
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
    security_group_name: str = field(default_factory=lambda: os.getenv("LCW_SECURITY_GROUP", "launch-control-workstation"))
    version: str = "0.1"

    @property
    def tags(self) -> dict[str, str]:
        """Build the canonical tag set applied to every managed AWS resource.

        Keeping this mapping in one property ensures discovery tags and ownership
        metadata remain identical for instances, volumes, key pairs, and security
        groups.  A new dictionary is returned so callers cannot mutate ``Config``.
        """
        return {
            "Project": self.project,
            "Role": "ControlWorkstation",
            "ManagedBy": "launch-control-workstation",
            "Owner": self.owner,
            "Environment": self.environment,
            "Version": self.version,
        }
