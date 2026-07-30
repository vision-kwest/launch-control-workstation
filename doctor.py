#!/usr/bin/env python3
"""Validate launch prerequisites without modifying AWS resources."""

from controlworkstation.config import Config
from controlworkstation.doctor import diagnose
from controlworkstation import logging


def main() -> int:
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
