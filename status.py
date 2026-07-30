#!/usr/bin/env python3
"""Show the managed control workstation's status."""

from __future__ import annotations

from controlworkstation import logging
from controlworkstation.aws import AwsError, find_instances
from controlworkstation.config import Config
from controlworkstation.health import check


def main() -> int:
    try:
        config = Config()
        instances = find_instances(config)
        if not instances:
            logging.info(f"No control workstation found in {config.region}.")
            return 0
        for instance in instances:
            print("Infrastructure\n")
            running = instance.state == "running"
            print(f"{'✔' if running else '✘'} {instance.state.capitalize()}")
            print(f"Public IP:        {instance.public_ip or '-'}")
            print(f"Public DNS:       {instance.public_dns or '-'}")
            print(f"Instance ID:      {instance.instance_id}")
            print(f"Launch Time:      {instance.launch_time or '-'}")
            print(f"Instance Type:    {instance.instance_type or '-'}")
            print(f"Disk Size:        {f'{instance.disk_size} GB' if instance.disk_size else '-'}")
            print(f"Region:           {config.region}")
            print(f"AZ:               {instance.availability_zone or '-'}")
            if not running or not instance.public_ip:
                print("\nOverall\n\nUNHEALTHY")
                return 1
            report = check(instance.public_ip, config)
            print("\nBootstrap\n")
            print(f"{'✔' if 'status: done' in report.cloud_init else '✘'} {report.cloud_init or 'cloud-init unavailable'}")
            print(f"{'✔' if report.bootstrap_completed else '✘'} Completed: {report.bootstrap_completed or 'unavailable'}")
            print("\nTools\n")
            for value in (report.tofu, report.git, report.gh, report.python):
                print(f"{'✔' if value else '✘'} {value or 'unavailable'}")
            print(f"\nSSH\n\n{'✔' if report.ssh == 'READY' else '✘'} {'Login verified' if report.ssh == 'READY' else 'Unavailable'}")
            print(f"\nOverall\n\n{'HEALTHY' if report.healthy else 'UNHEALTHY'}")
            if report.errors:
                print("\nFailures:\n  - " + "\n  - ".join(report.errors))
            if not report.healthy:
                return 1
        return 0
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
