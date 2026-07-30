#!/usr/bin/env python3
"""Open an SSH session to the running control workstation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from controlworkstation import logging
from controlworkstation.aws import AwsError, find_instances
from controlworkstation.config import Config
from controlworkstation.ssh import connect


def main(argv: Sequence[str] | None = None) -> int:
    """Open an interactive session to the newest running managed workstation.

    Discovery is restricted to running instances and returns newest-first.  The
    command refuses to invoke SSH without a public IP, then propagates the SSH
    process's own exit status.  Discovery and configuration failures are rendered
    through the shared logger and normalized to status 1.
    """
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        config = Config()
        running = find_instances(config, states=("running",))
        if not running:
            raise RuntimeError(f"No running control workstation found in {config.region}")
        if not running[0].public_ip:
            raise RuntimeError("The running workstation has no public IP address")
        return connect(running[0].public_ip, config)
    except (AwsError, RuntimeError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
