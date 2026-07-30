"""Configuration, with environment variable overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _integer(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True)
class Config:
    region: str = field(default_factory=lambda: os.getenv("LCW_REGION", "us-east-1"))
    instance_type: str = field(default_factory=lambda: os.getenv("LCW_INSTANCE_TYPE", "t3.large"))
    disk_size: int = field(default_factory=lambda: _integer("LCW_DISK_SIZE", 100))
    owner: str = field(default_factory=lambda: os.getenv("LCW_OWNER", os.getenv("USER", "studio")))
    project: str = field(default_factory=lambda: os.getenv("LCW_PROJECT", "StudioInfrastructure"))
    environment: str = field(default_factory=lambda: os.getenv("LCW_ENVIRONMENT", "development"))
    ssh_timeout: int = field(default_factory=lambda: _integer("LCW_SSH_TIMEOUT", 600))
    ssh_cidr: str = field(default_factory=lambda: os.getenv("LCW_SSH_CIDR", "0.0.0.0/0"))
    public_key: Path = field(default_factory=lambda: Path(os.getenv("LCW_PUBLIC_KEY", "~/.ssh/id_ed25519.pub")).expanduser())
    key_name: str = field(default_factory=lambda: os.getenv("LCW_KEY_NAME", "launch-control-workstation"))
    security_group_name: str = field(default_factory=lambda: os.getenv("LCW_SECURITY_GROUP", "launch-control-workstation"))
    version: str = "0.1"

    @property
    def tags(self) -> dict[str, str]:
        return {
            "Project": self.project,
            "Role": "ControlWorkstation",
            "ManagedBy": "launch-control-workstation",
            "Owner": self.owner,
            "Environment": self.environment,
            "Version": self.version,
        }
