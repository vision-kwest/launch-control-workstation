#!/usr/bin/env python3
"""Provision the studio infrastructure control workstation."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time

from controlworkstation import logging
from controlworkstation.aws import AwsError, aws, default_network, describe_instance, ensure_key_pair, ensure_security_group, find_instances, tag_spec
from controlworkstation.config import Config
from controlworkstation.health import authenticate, check, wait_for_cloud_init
from controlworkstation.ssh import connect
from controlworkstation.userdata import render
from controlworkstation.wait import ssh as wait_for_ssh


def verify_tools() -> None:
    """Validate local prerequisites before making any AWS-side changes.

    Python is checked explicitly because the application relies on modern type
    syntax and runtime behavior.  ``aws`` and ``git`` are located through PATH;
    failing early gives operators a clear prerequisite error instead of leaving
    partially provisioned infrastructure after a later subprocess failure.

    Raises:
        RuntimeError: If Python is older than 3.12 or a required executable is
            unavailable.
    """
    logging.info(f"Checking Python {sys.version_info.major}.{sys.version_info.minor}...")
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or newer is required")
    for executable in ("aws", "git"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required executable '{executable}' was not found in PATH")
    logging.ok("Python, AWS CLI, and Git are available.")


def launch(config: Config) -> str:
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

    existing = find_instances(config)
    if existing:
        instance = existing[0]
        if instance.state == "stopped":
            logging.info(f"Starting existing instance {instance.instance_id}...")
            aws(["ec2", "start-instances", "--instance-ids", instance.instance_id], config)
        else:
            logging.ok(f"Reusing existing {instance.state} instance {instance.instance_id}.")
        return instance.instance_id

    logging.info("Locating the latest Ubuntu 24.04 LTS x86_64 AMI...")
    parameter = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    ami = aws(["ssm", "get-parameter", "--name", parameter], config)["Parameter"]["Value"]
    logging.ok(f"Using AMI {ami}.")

    vpc_id, subnet_id = default_network(config)
    group_id = ensure_security_group(vpc_id, config)
    ensure_key_pair(config)
    logging.info("Creating EC2 instance...")
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
    return data["Instances"][0]["InstanceId"]


def main() -> int:
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
    args = parser.parse_args()
    total_started = time.monotonic()
    try:
        config = Config()
        verify_tools()
        creation_started = time.monotonic()
        instance_id = launch(config)
        logging.info("Waiting for instance-running...")
        aws(["ec2", "wait", "instance-running", "--instance-ids", instance_id], config, json_output=False)
        logging.ok("Instance running.")
        logging.info("Waiting for instance-status-ok...")
        aws(["ec2", "wait", "instance-status-ok", "--instance-ids", instance_id], config, json_output=False)
        logging.ok("Instance status checks passed.")
        logging.ok(f"Instance creation completed in {time.monotonic() - creation_started:.1f}s.")
        instance = describe_instance(instance_id, config)
        if not instance.public_ip:
            raise AwsError("Instance is running but has no public IP address")
        ssh_started = time.monotonic()
        logging.info("Waiting for SSH availability...")
        wait_for_ssh(instance.public_ip, config.ssh_timeout)
        authenticate(instance.public_ip, config)
        logging.ok(f"SSH authentication verified. ({time.monotonic() - ssh_started:.1f}s)")
        cloud_started = time.monotonic()
        logging.info("Waiting for cloud-init to complete (reconnections are automatic)...")
        wait_for_cloud_init(instance.public_ip, config)
        logging.ok(f"cloud-init complete. ({time.monotonic() - cloud_started:.1f}s)")
        report = check(instance.public_ip, config)
        if not report.healthy:
            raise RuntimeError("Health verification failed:\n  - " + "\n  - ".join(report.errors))
        logging.ok("All workstation health checks passed.")
        logging.ok(f"Total launch time: {time.monotonic() - total_started:.1f}s.")
        print("\n----------------------------------\nControl Workstation Ready\n")
        print(f"Instance ID: {instance.instance_id}")
        print(f"Region:      {config.region}")
        print(f"Public IP:   {instance.public_ip}")
        print(f"Public DNS:  {instance.public_dns or '-'}")
        print("\nOption 1 (continue from CloudShell)\n\n  python3 ssh.py")
        print("\nOption 2 (connect from another computer)\n")
        print(f"  ssh -i {config.public_key.with_suffix('')} ubuntu@{instance.public_ip}")
        print("----------------------------------")
        if args.login or config.auto_login:
            return connect(instance.public_ip, config)
        return 0
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
