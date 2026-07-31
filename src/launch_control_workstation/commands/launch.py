#!/usr/bin/env python3
"""Provision the studio infrastructure control workstation."""

from __future__ import annotations

import argparse
import tempfile
import time
from collections.abc import Sequence

from launch_control_workstation import logging
from launch_control_workstation.aws import AwsError, aws, default_network, describe_instance, ensure_key_pair, ensure_security_group, find_instances, tag_spec
from launch_control_workstation.config import Config
from launch_control_workstation.doctor import diagnose
from launch_control_workstation.health import authenticate, injected_key_health, wait_for_cloud_init, wait_until_healthy
from launch_control_workstation.ssh import connect
from launch_control_workstation.userdata import render
from launch_control_workstation.wait import ssh as wait_for_ssh


def verify_tools(config: Config) -> None:
    """Validate local prerequisites before making any AWS-side changes.

    Python is checked explicitly because the application relies on modern type
    syntax and runtime behavior.  ``aws`` and ``git`` are located through PATH;
    failing early gives operators a clear prerequisite error instead of leaving
    partially provisioned infrastructure after a later subprocess failure.

    Raises:
        RuntimeError: If Python is older than 3.10 or a required executable is
            unavailable.
    """
    logging.info("Running preflight diagnostics...")
    checks = diagnose(config)
    # A completely absent pair passes diagnostics because launch creates it;
    # incomplete, invalid, or insecure existing key material remains fatal.
    failures = [item for item in checks if not item.passed]
    if failures:
        raise RuntimeError("Preflight failed:\n  - " + "\n  - ".join(f"{x.name}: {x.detail}" for x in failures))
    logging.ok("Preflight diagnostics passed.")


def launch(config: Config, *, replace_key_pair: bool = False) -> str:
    """Reuse or create the managed EC2 workstation and return its instance ID.

    Credentials are proven first.  The newest existing managed instance is
    reused, with stopped instances started in place.  Otherwise the current
    Canonical Ubuntu 24.04 AMI is resolved through SSM, default networking and
    access resources are ensured, and rendered cloud-init is passed through a
    temporary file to ``run-instances``.  The new instance uses encrypted gp3
    storage, IMDSv2, detailed monitoring, management tags, and termination on
    guest shutdown.  This function starts provisioning but does not wait for EC2,
    SSH, or bootstrap readiness; :func:`main` owns those lifecycle gates.

    Raises:
        AwsError: If authentication or any AWS/resource preparation step fails.
    """
    logging.info("Checking AWS credentials...")
    identity = aws(["sts", "get-caller-identity"], config)
    logging.ok(f"AWS authentication successful ({identity['Arn']}).")

    # Do this before reuse too: a launcher must never proceed with an unverified key.
    existing = find_instances(config)
    if replace_key_pair and existing:
        raise AwsError(
            "--replace-key-pair cannot be used while a managed workstation exists; "
            "destroy it first or choose a different LCW_KEY_NAME"
        )
    ensure_key_pair(config, replace=replace_key_pair)
    if existing:
        instance = existing[0]
        if instance.state == "stopped":
            logging.info(f"Starting existing instance {instance.instance_id}...")
            aws(["ec2", "start-instances", "--instance-ids", instance.instance_id], config)
        else:
            logging.ok(f"Reusing existing {instance.state} instance {instance.instance_id}.")
        return instance.instance_id

    ami_started = time.monotonic()
    logging.info("Locating the latest Ubuntu 24.04 LTS x86_64 AMI...")
    parameter = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    ami = aws(["ssm", "get-parameter", "--name", parameter], config)["Parameter"]["Value"]
    logging.ok(f"Using AMI {ami}. ({time.monotonic() - ami_started:.1f}s)")

    vpc_id, subnet_id = default_network(config)
    group_id = ensure_security_group(vpc_id, config)
    logging.info("Creating EC2 instance...")
    create_started = time.monotonic()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml") as user_data:
        user_data.write(render())
        user_data.flush()
        data = aws([
            "ec2", "run-instances", "--image-id", ami, "--instance-type", config.instance_type,
            "--key-name", config.key_name, "--subnet-id", subnet_id, "--security-group-ids", group_id,
            "--associate-public-ip-address", "--ebs-optimized", "--monitoring", "Enabled=true",
            "--instance-initiated-shutdown-behavior", "terminate",
            "--metadata-options", "HttpTokens=required,HttpEndpoint=enabled",
            "--block-device-mappings",
            f"DeviceName=/dev/sda1,Ebs={{VolumeSize={config.disk_size},VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}}",
            "--tag-specifications", tag_spec("instance", config.tags), tag_spec("volume", config.tags),
            "--user-data", f"file://{user_data.name}",
        ], config)
    instance_id = data["Instances"][0]["InstanceId"]
    logging.ok(f"Created EC2 instance {instance_id}. ({time.monotonic() - create_started:.1f}s)")
    return instance_id


def main(argv: Sequence[str] | None = None) -> int:
    """Run the complete launch, readiness, health-check, and optional-login flow.

    After parsing CLI preferences, this orchestration function measures each
    major phase, waits for both EC2 waiter states, resolves the public address,
    verifies network and key-based SSH access, survives cloud-init reconnects,
    and requires every health probe to pass.  It then prints reproducible login
    instructions and optionally replaces the final success with the interactive
    SSH client's exit status.  Expected operational failures are reported as a
    concise error and converted to exit status 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", action="store_true", help="open an SSH session after successful health checks")
    parser.add_argument(
        "--replace-key-pair",
        action="store_true",
        help="replace a mismatched EC2 key-pair registration (requires no managed workstation)",
    )
    args = parser.parse_args(argv)
    total_started = time.monotonic()
    try:
        config = Config()
        verify_tools(config)
        instance_id = launch(config, replace_key_pair=args.replace_key_pair)
        running_started = time.monotonic()
        logging.info("Waiting for instance-running...")
        aws(["ec2", "wait", "instance-running", "--instance-ids", instance_id], config, json_output=False)
        logging.ok(f"Instance running. ({time.monotonic() - running_started:.1f}s)")
        status_started = time.monotonic()
        logging.info("Waiting for instance-status-ok...")
        aws(["ec2", "wait", "instance-status-ok", "--instance-ids", instance_id], config, json_output=False)
        logging.ok(f"Instance status checks passed. ({time.monotonic() - status_started:.1f}s)")
        instance = describe_instance(instance_id, config)
        if not instance.public_ip:
            raise AwsError("Instance is running but has no public IP address")
        injected_key = injected_key_health(instance, config)
        if not injected_key.passed:
            raise RuntimeError(f"Incorrect SSH key injected into {instance.instance_id}: "
                               f"expected {config.key_name}, found {injected_key.detail}")
        ssh_started = time.monotonic()
        logging.info("Waiting for SSH availability...")
        wait_for_ssh(instance.public_ip, config.ssh_timeout)
        authentication = authenticate(instance.public_ip, config)
        if not authentication.passed:
            raise RuntimeError(f"SSH authentication failed: {authentication.detail}")
        logging.ok(f"SSH authentication verified. ({time.monotonic() - ssh_started:.1f}s)")
        cloud_started = time.monotonic()
        logging.info("Waiting for cloud-init to complete (reconnections are automatic)...")
        wait_for_cloud_init(instance.public_ip, config)
        logging.ok(f"cloud-init complete. ({time.monotonic() - cloud_started:.1f}s)")
        health_started = time.monotonic()
        logging.info("Waiting for all workstation health checks...")
        report = wait_until_healthy(instance, config)
        logging.ok(f"Health checks passed. ({time.monotonic() - health_started:.1f}s)")
        logging.ok("All workstation health checks passed.")
        logging.ok(f"Total launch time: {time.monotonic() - total_started:.1f}s.")
        print("\n==================================================\n\nControl Workstation Ready\n")
        print(f"Instance ID: {instance.instance_id}")
        print(f"Region:      {config.region}")
        print(f"Availability Zone: {instance.availability_zone}")
        print(f"Public IP:   {instance.public_ip}")
        print(f"Public DNS:  {instance.public_dns or '-'}")
        print("Health:      READY")
        print("\nNext Steps\n\nOption 1\nContinue from this CloudShell\n\n  workstation ssh")
        print("\nOption 2\nConnect from another computer\n")
        print(f"  ssh -i {config.public_key.with_suffix('')} ubuntu@{instance.public_ip}")
        print("\nOption 3\nVS Code Remote SSH\n")
        print("  Host control-workstation")
        print(f"    HostName {instance.public_ip}")
        print("    User ubuntu")
        print(f"    IdentityFile {config.public_key.with_suffix('')}")
        print("\n==================================================")
        if args.login or config.auto_login:
            return connect(instance.public_ip, config)
        return 0
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
