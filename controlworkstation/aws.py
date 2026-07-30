"""AWS CLI subprocess adapter and EC2 operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
from typing import Any, Sequence

from .config import Config


class AwsError(RuntimeError):
    """An AWS CLI command failed."""


def aws(args: Sequence[str], config: Config, *, json_output: bool = True) -> Any:
    command = ["aws", *args, "--region", config.region, "--no-cli-pager"]
    if json_output:
        command.extend(["--output", "json"])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown AWS CLI error"
        raise AwsError(f"Command failed: {' '.join(command)}\n{detail}")
    if not json_output or not result.stdout.strip():
        return result.stdout.strip()
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AwsError(f"AWS CLI returned invalid JSON: {exc}") from exc


def tag_spec(resource_type: str, tags: dict[str, str]) -> str:
    return json.dumps({
        "ResourceType": resource_type,
        "Tags": [{"Key": key, "Value": value} for key, value in sorted(tags.items())],
    })


@dataclass(frozen=True)
class Instance:
    instance_id: str
    state: str
    public_ip: str = ""
    public_dns: str = ""
    availability_zone: str = ""
    launch_time: str = ""
    instance_type: str = ""
    disk_size: int | None = None


def find_instances(config: Config, *, states: Sequence[str] = ("pending", "running", "stopping", "stopped")) -> list[Instance]:
    data = aws(
        ["ec2", "describe-instances", "--filters",
         "Name=tag:ManagedBy,Values=launch-control-workstation",
         "Name=tag:Role,Values=ControlWorkstation",
         f"Name=instance-state-name,Values={','.join(states)}"],
        config,
    )
    found: list[Instance] = []
    for reservation in data.get("Reservations", []):
        for item in reservation.get("Instances", []):
            volumes = item.get("BlockDeviceMappings", [])
            disk_size = None
            if volumes:
                volume_id = volumes[0].get("Ebs", {}).get("VolumeId")
                if volume_id:
                    volume = aws(["ec2", "describe-volumes", "--volume-ids", volume_id], config)
                    disk_size = volume["Volumes"][0]["Size"]
            found.append(Instance(
                item["InstanceId"], item["State"]["Name"],
                item.get("PublicIpAddress", ""), item.get("PublicDnsName", ""),
                item.get("Placement", {}).get("AvailabilityZone", ""),
                item.get("LaunchTime", ""), item.get("InstanceType", ""), disk_size,
            ))
    return sorted(found, key=lambda instance: instance.launch_time, reverse=True)


def describe_instance(instance_id: str, config: Config) -> Instance:
    instances = find_instances(config, states=("pending", "running", "stopping", "stopped", "shutting-down"))
    for instance in instances:
        if instance.instance_id == instance_id:
            return instance
    raise AwsError(f"Instance {instance_id} was not found")


def default_network(config: Config) -> tuple[str, str]:
    vpcs = aws(["ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true"], config)["Vpcs"]
    if not vpcs:
        raise AwsError(f"No default VPC exists in {config.region}")
    vpc_id = vpcs[0]["VpcId"]
    subnets = aws(["ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}", "Name=default-for-az,Values=true"], config)["Subnets"]
    if not subnets:
        raise AwsError("The default VPC has no default subnet")
    return vpc_id, sorted(subnets, key=lambda item: item["AvailabilityZone"])[0]["SubnetId"]


def ensure_security_group(vpc_id: str, config: Config) -> str:
    groups = aws(["ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={vpc_id}", f"Name=group-name,Values={config.security_group_name}"], config)["SecurityGroups"]
    if groups:
        return groups[0]["GroupId"]
    data = aws(["ec2", "create-security-group", "--group-name", config.security_group_name,
                "--description", "SSH access to the studio control workstation", "--vpc-id", vpc_id,
                "--tag-specifications", tag_spec("security-group", config.tags)], config)
    group_id = data["GroupId"]
    aws(["ec2", "authorize-security-group-ingress", "--group-id", group_id,
         "--protocol", "tcp", "--port", "22", "--cidr", config.ssh_cidr], config)
    return group_id


def ensure_key_pair(config: Config) -> None:
    private_key = config.public_key.with_suffix("")
    if not private_key.exists() and not config.public_key.exists():
        private_key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(private_key),
                                 "-N", "", "-C", "launch-control-workstation"],
                                text=True, capture_output=True, check=False)
        if result.returncode:
            raise AwsError(f"Could not create SSH key: {result.stderr.strip()}")
        print(f"Created a new ED25519 SSH key: {private_key} (public key: {config.public_key})")
    elif not private_key.is_file() or not config.public_key.is_file():
        raise AwsError(f"Incomplete SSH key pair: both {private_key} and {config.public_key} must exist; no files were overwritten")

    existing = aws(["ec2", "describe-key-pairs", "--filters", f"Name=key-name,Values={config.key_name}"], config)["KeyPairs"]
    if existing:
        remote_fingerprint = existing[0].get("KeyFingerprint", "")
    else:
        imported = aws(["ec2", "import-key-pair", "--key-name", config.key_name,
         "--public-key-material", f"fileb://{config.public_key}",
         "--tag-specifications", tag_spec("key-pair", config.tags)], config)
        remote_fingerprint = imported.get("KeyFingerprint", "")
    fingerprint = subprocess.run(["ssh-keygen", "-lf", str(config.public_key)],
                                 text=True, capture_output=True, check=False)
    if fingerprint.returncode:
        raise AwsError(f"Invalid SSH public key {config.public_key}: {fingerprint.stderr.strip()}")
    local_fingerprint = fingerprint.stdout.split()[1]
    if remote_fingerprint and local_fingerprint != remote_fingerprint:
        raise AwsError(f"EC2 key pair '{config.key_name}' does not match {config.public_key} "
                       f"(EC2 {remote_fingerprint}, local {local_fingerprint}). Use a different LCW_KEY_NAME or remove the stale EC2 key pair.")
