"""Render cloud-init user data with the bootstrap script embedded."""

from __future__ import annotations

import shlex
from pathlib import Path

from .config import Config

ROOT = Path(__file__).resolve().parent


def render(config: Config | None = None) -> str:
    """Embed the bootstrap shell script into the cloud-init YAML template.

    Cloud-init's YAML block scalar requires six spaces before every script line,
    so the raw script is transformed line by line before replacing the unique
    placeholder.  Reading both assets relative to the package root makes output
    independent of the caller's current working directory.

    Returns:
        Complete cloud-init user data suitable for EC2's ``--user-data`` option.
    """
    config = config or Config()
    template = (ROOT / "templates" / "cloud-init.yaml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    script = script.replace("__LCW_REGION__", shlex.quote(config.region))
    script = script.replace("__LCW_KEY_NAME__", shlex.quote(config.key_name))
    indented = "\n".join(f"      {line}" for line in script.splitlines())
    return template.replace("      __BOOTSTRAP_SCRIPT__", indented)
