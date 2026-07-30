#!/usr/bin/env python3
"""Provision the studio infrastructure control workstation."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile

from controlworkstation import logging
from controlworkstation.aws import AwsError, aws, default_network, describe_instance, ensure_key_pair, ensure_security_group, find_instances, tag_spec
from controlworkstation.config import Config
from controlworkstation.userdata import render
from controlworkstation.wait import ssh as wait_for_ssh


def verify_tools() -> None:
    logging.info(f"Checking Python {sys.version_info.major}.{sys.version_info.minor}...")
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or newer is required")
    for executable in ("aws", "git"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required executable '{executable}' was not found in PATH")
    logging.ok("Python, AWS CLI, and Git are available.")


def launch(config: Config) -> str:
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
    try:
        config = Config()
        verify_tools()
        instance_id = launch(config)
        logging.info("Waiting for instance-running...")
        aws(["ec2", "wait", "instance-running", "--instance-ids", instance_id], config, json_output=False)
        logging.ok("Instance running.")
        logging.info("Waiting for instance-status-ok...")
        aws(["ec2", "wait", "instance-status-ok", "--instance-ids", instance_id], config, json_output=False)
        logging.ok("Instance status checks passed.")
        instance = describe_instance(instance_id, config)
        if not instance.public_ip:
            raise AwsError("Instance is running but has no public IP address")
        logging.info("Waiting for SSH...")
        wait_for_ssh(instance.public_ip, config.ssh_timeout)
        logging.ok("SSH available.")
        print("\n==================================\nControl Workstation Ready\n")
        print(f"Instance:   {instance.instance_id}")
        print(f"Public IP: {instance.public_ip}")
        print(f"Public DNS: {instance.public_dns}")
        print(f"AZ:         {instance.availability_zone}")
        print(f"SSH:        ssh -i {config.public_key.with_suffix('')} ubuntu@{instance.public_ip}")
        print("==================================")
        return 0
    except (AwsError, RuntimeError, TimeoutError, ValueError) as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
