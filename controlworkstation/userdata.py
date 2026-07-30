"""Render cloud-init user data with the bootstrap script embedded."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def render() -> str:
    """Embed the maintained bootstrap shell script into the cloud-init template.

    Cloud-config block scalars require six spaces beneath ``content``, so each
    bootstrap line is indented before replacing the unique placeholder.  Reading
    both source files at launch time keeps the executable script independently
    testable while returning one complete user-data document to EC2.
    """
    template = (ROOT / "templates" / "cloud-init.yaml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    indented = "\n".join(f"      {line}" for line in script.splitlines())
    return template.replace("      __BOOTSTRAP_SCRIPT__", indented)
