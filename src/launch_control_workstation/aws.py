"""AWS CLI subprocess adapter and EC2 operations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .config import Config
from .process import run


class AwsError(RuntimeError):
    """An AWS CLI command failed."""


def aws(args: Sequence[str], config: Config, *, json_output: bool = True) -> Any:
    """Execute one AWS CLI operation with the workstation's global options.

    The region and pager suppression flags are appended uniformly so every
    operation targets the configured region and remains safe in unattended
    processes.  JSON output is requested and decoded by default; waiter-style
    calls can disable it and receive stripped text instead.  The command is run
    without ``check=True`` so this adapter can include AWS's stderr in a stable,
    domain-specific exception.

    Raises:
        AwsError: If the CLI exits unsuccessfully or claims to return JSON that
            cannot be decoded.
    """
    command = ["aws", *args, "--region", config.region, "--no-cli-pager"]
    if json_output:
        command.extend(["--output", "json"])
    result = run(command)
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
    """Serialize tags in the shape expected by ``--tag-specifications``.

    Sorting dictionary items makes the generated JSON deterministic for tests,
    logs, and troubleshooting while :func:`json.dumps` safely preserves spaces
    and escapes arbitrary tag values.
    """
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
    key_name: str = ""
    disk_size: int | None = None


def find_instances(config: Config, *, states: Sequence[str] = ("pending", "running", "stopping", "stopped")) -> list[Instance]:
    """Discover managed EC2 instances and enrich them with root-volume size.

    EC2 is filtered by the two canonical management tags plus the caller's
    allowed lifecycle states.  Each returned reservation is flattened into an
    :class:`Instance`; when a first block-device mapping has an EBS volume, an
    additional API call obtains its size.  Results are newest-first so callers
    that reuse index zero consistently choose the most recent workstation.
    """
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
                item.get("LaunchTime", ""), item.get("InstanceType", ""),
                item.get("KeyName", ""), disk_size,
            ))
    return sorted(found, key=lambda instance: instance.launch_time, reverse=True)


def describe_instance(instance_id: str, config: Config) -> Instance:
    """Return one managed instance by ID across all relevant live states.

    This intentionally delegates to :func:`find_instances`, preserving its tag
    boundary: an unrelated EC2 instance is considered not found even if its ID
    is valid.  ``shutting-down`` is included for accurate post-launch lookups.

    Raises:
        AwsError: If no managed instance with ``instance_id`` is discoverable.
    """
    instances = find_instances(config, states=("pending", "running", "stopping", "stopped", "shutting-down"))
    for instance in instances:
        if instance.instance_id == instance_id:
            return instance
    raise AwsError(f"Instance {instance_id} was not found")


def default_network(config: Config) -> tuple[str, str]:
    """Select the configured region's default VPC and a deterministic subnet.

    Only subnets marked as default for their Availability Zone are considered.
    Sorting by Availability Zone avoids relying on AWS response order and makes
    repeated launches choose consistently when several default subnets exist.

    Raises:
        AwsError: If the region has no default VPC or it has no default subnet.
    """
    vpcs = aws(["ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true"], config)["Vpcs"]
    if not vpcs:
        raise AwsError(f"No default VPC exists in {config.region}")
    vpc_id = vpcs[0]["VpcId"]
    subnets = aws(["ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}", "Name=default-for-az,Values=true"], config)["Subnets"]
    if not subnets:
        raise AwsError("The default VPC has no default subnet")
    return vpc_id, sorted(subnets, key=lambda item: item["AvailabilityZone"])[0]["SubnetId"]


def ensure_security_group(vpc_id: str, config: Config) -> str:
    """Find or create the named SSH security group and return its ID.

    Existing groups are reused without rewriting their ingress rules.  For a
    newly created group, management tags are attached at creation and TCP port
    22 is authorized from ``config.ssh_cidr``.  Consequently, changing the CIDR
    later does not implicitly modify a group operators may have customized.
    """
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


def ensure_key_pair(config: Config, *, replace: bool = False) -> None:
    """Ensure matching local Ed25519 files and an EC2 key-pair registration.

    If neither local key file exists, ``ssh-keygen`` creates the pair without a
    passphrase for unattended launch and health checks.  A half-present pair is
    rejected to avoid overwriting or silently changing credentials.  The public
    key is imported into EC2 when necessary, then local and remote fingerprints
    are compared so a reused EC2 key-pair name cannot lock the user out.  When
    ``replace`` is explicitly requested, a mismatched EC2 registration is
    deleted and re-imported; local key material is never changed.

    Raises:
        AwsError: If key generation or validation fails, local files are
            incomplete, or the EC2 fingerprint differs from the local key.
    """
    private_key = config.public_key.with_suffix("")
    if not private_key.exists() and not config.public_key.exists():
        private_key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = run(["ssh-keygen", "-t", "ed25519", "-f", str(private_key),
                      "-N", "", "-C", "launch-control-workstation"])
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
    fingerprint = run(["ssh-keygen", "-lf", str(config.public_key)])
    if fingerprint.returncode:
        raise AwsError(f"Invalid SSH public key {config.public_key}: {fingerprint.stderr.strip()}")
    local_fingerprint = fingerprint.stdout.split()[1]
    # EC2 returns imported Ed25519 SHA-256 fingerprints as bare base64, while
    # OpenSSH prefixes the same digest with ``SHA256:``.
    comparable_remote = remote_fingerprint.removeprefix("SHA256:")
    comparable_local = local_fingerprint.removeprefix("SHA256:")
    if comparable_remote and comparable_local != comparable_remote:
        if not replace:
            raise AwsError(
                f"EC2 key pair '{config.key_name}' does not match {config.public_key} "
                f"(EC2 {remote_fingerprint}, local {local_fingerprint}). "
                "Rerun with --replace-key-pair to replace only the EC2 registration, "
                "or use a different LCW_KEY_NAME."
            )
        aws(["ec2", "delete-key-pair", "--key-name", config.key_name], config)
        aws(["ec2", "import-key-pair", "--key-name", config.key_name,
             "--public-key-material", f"fileb://{config.public_key}",
             "--tag-specifications", tag_spec("key-pair", config.tags)], config)
