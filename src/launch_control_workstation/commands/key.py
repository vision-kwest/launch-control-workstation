#!/usr/bin/env python3
"""Create, register, and display the Control Workstation SSH identity."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from launch_control_workstation import logging
from launch_control_workstation.aws import AwsError, aws, ensure_key_pair
from launch_control_workstation.config import Config
from launch_control_workstation.process import run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace a mismatched EC2 registration; local key files are never replaced",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="validate and display the existing identity without creating resources",
    )
    args = parser.parse_args(argv)
    try:
        config = Config()
        private_key = config.public_key.with_suffix("")
        if args.check:
            if not private_key.is_file() or not config.public_key.is_file():
                raise AwsError("Control Workstation SSH key pair is incomplete or missing")
        else:
            ensure_key_pair(
                config,
                replace=args.replace,
                mismatch_recovery="workstation key --replace",
            )

        fingerprint = run(["ssh-keygen", "-lf", str(config.public_key)])
        if fingerprint.returncode:
            raise AwsError(f"Invalid SSH public key {config.public_key}: {fingerprint.stderr.strip()}")
        local = fingerprint.stdout.split()[1]
        pairs = aws(["ec2", "describe-key-pairs", "--key-names", config.key_name], config)["KeyPairs"]
        if not pairs:
            raise AwsError(f"EC2 key pair '{config.key_name}' is not registered")
        remote = pairs[0].get("KeyFingerprint", "")
        if local.removeprefix("SHA256:") != remote.removeprefix("SHA256:"):
            raise AwsError(
                f"EC2 key pair '{config.key_name}' fingerprint differs "
                f"(EC2 {remote}, local {local})"
            )
        print(f"Fingerprint: {local}")
        print(f"EC2 key name: {config.key_name}")
        print(f"Public key: {config.public_key}")
        print(f"Private key: {private_key}")
        return 0
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
