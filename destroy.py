#!/usr/bin/env python3
"""Terminate managed control workstation instances."""

from __future__ import annotations

import argparse

from controlworkstation import logging
from controlworkstation.aws import AwsError, aws, find_instances
from controlworkstation.config import Config


def main() -> int:
    """Confirm, terminate, and wait for every active managed workstation.

    All instances selected by the utility's management tags are displayed before any
    destructive call.  Interactive users must explicitly confirm unless ``--yes``
    was supplied for automation.  Waiting for EC2's terminated state makes successful
    return a reliable cleanup signal; cancellation and an already-empty environment
    are harmless status-0 outcomes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
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
