#!/usr/bin/env python3
"""Terminate managed control workstation instances."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from controlworkstation import logging
from controlworkstation.aws import AwsError, aws, find_instances
from controlworkstation.config import Config


def main(argv: Sequence[str] | None = None) -> int:
    """Find, confirm, terminate, and wait for all managed workstations.

    The ``--yes`` flag supports automation; otherwise only explicit ``y`` or
    ``yes`` confirmation proceeds.  An empty discovery result and a user
    cancellation are both successful no-ops.  Termination is submitted for all
    discovered IDs in one call, followed by the EC2 waiter so a success message
    guarantees the instances reached the terminated state.  Known input,
    configuration, and AWS failures are logged and returned as exit status 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)
    try:
        config = Config()
        instances = find_instances(config)
        if not instances:
            logging.ok("No control workstation exists.")
            return 0
        ids = [item.instance_id for item in instances]
        print(f"Instances to terminate: {', '.join(ids)}")
        if not args.yes and input("Are you sure? [y/N] ").strip().lower() not in {"y", "yes"}:
            logging.info("Cancelled.")
            return 0
        logging.info("Terminating control workstation...")
        aws(["ec2", "terminate-instances", "--instance-ids", *ids], config)
        aws(["ec2", "wait", "instance-terminated", "--instance-ids", *ids], config, json_output=False)
        logging.ok("Control workstation terminated.")
        return 0
    except (AwsError, EOFError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
