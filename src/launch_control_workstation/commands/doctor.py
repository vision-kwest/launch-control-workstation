#!/usr/bin/env python3
"""Validate launch prerequisites without modifying AWS resources."""

import argparse
from collections.abc import Sequence

from launch_control_workstation import logging
from launch_control_workstation.config import Config
from launch_control_workstation.doctor import diagnose


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        checks = diagnose(Config())
    except (RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1
    print("Control Workstation Doctor\n")
    for item in checks:
        print(f"{'PASS' if item.passed else 'FAIL':4}  {item.name}: {item.detail}")
    passed = all(item.passed for item in checks)
    print(f"\nOverall: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
