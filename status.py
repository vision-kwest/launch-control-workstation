#!/usr/bin/env python3
"""Show the managed control workstation's status."""

from __future__ import annotations

from controlworkstation import logging
from controlworkstation.aws import AwsError, find_instances
from controlworkstation.config import Config


def main() -> int:
    try:
        config = Config()
        instances = find_instances(config)
        if not instances:
            logging.info(f"No control workstation found in {config.region}.")
            return 0
        for instance in instances:
            print(f"State:            {instance.state.capitalize()}")
            print(f"Public IP:        {instance.public_ip or '-'}")
            print(f"Public DNS:       {instance.public_dns or '-'}")
            print(f"Instance ID:      {instance.instance_id}")
            print(f"Launch Time:      {instance.launch_time or '-'}")
            print(f"Instance Type:    {instance.instance_type or '-'}")
            print(f"Disk Size:        {f'{instance.disk_size} GB' if instance.disk_size else '-'}")
            print(f"Region:           {config.region}")
            print(f"AZ:               {instance.availability_zone or '-'}")
            print("OpenTofu Version: unavailable (log in to run 'tofu version')")
        return 0
    except (AwsError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
