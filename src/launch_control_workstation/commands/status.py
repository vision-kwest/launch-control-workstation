#!/usr/bin/env python3
"""Display the Control Workstation health dashboard."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from launch_control_workstation import logging
from launch_control_workstation.aws import AwsError, find_instances
from launch_control_workstation.config import Config
from launch_control_workstation.health import Check, check


def section(title: str, checks: tuple[Check, ...]) -> None:
    print(f"{title}\n")
    for item in checks:
        print(f"{'✔' if item.passed else '✘'} {item.name}: {item.detail}")
    print()


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        config = Config()
        instances = find_instances(config)
        if not instances:
            logging.info(f"No Control Workstation found in {config.region}.")
            return 0
        overall = True
        for instance in instances:
            report = check(instance, config)
            section("Infrastructure", report.infrastructure)
            section("Connectivity", report.connectivity)
            section("Provisioning", report.provisioning)
            section("Developer Tools", report.tools)
            section("System", report.system)
            print("Overall\n")
            print("HEALTHY" if report.healthy else "UNHEALTHY")
            if len(instances) > 1:
                print("\n" + "=" * 50 + "\n")
            overall = overall and report.healthy
        return 0 if overall else 1
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
