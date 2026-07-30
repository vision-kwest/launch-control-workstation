"""Render cloud-init user data with the bootstrap script embedded."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def render() -> str:
    template = (ROOT / "templates" / "cloud-init.yaml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    indented = "\n".join(f"      {line}" for line in script.splitlines())
    return template.replace("      __BOOTSTRAP_SCRIPT__", indented)
