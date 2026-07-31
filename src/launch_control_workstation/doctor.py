"""Read-only preflight diagnostics shared by doctor.py and launch.py."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import sys

from .aws import AwsError, aws, default_network, find_instances
from .config import Config
from .process import run


@dataclass(frozen=True)
class Diagnostic:
    name: str
    passed: bool
    detail: str


def diagnose(config: Config) -> tuple[Diagnostic, ...]:
    """Run local and AWS checks without creating, changing, or deleting resources."""
    results = [Diagnostic("Python", sys.version_info >= (3, 10), sys.version.split()[0])]
    for name, executable in (("Git", "git"), ("AWS CLI", "aws"), ("SSH", "ssh"), ("SSH keygen", "ssh-keygen")):
        path = shutil.which(executable)
        results.append(Diagnostic(name, bool(path), path or "not found in PATH"))
    private = config.public_key.with_suffix("")
    pair_exists = private.is_file() and config.public_key.is_file()
    pair_absent = not private.exists() and not config.public_key.exists()
    secure_mode = not pair_exists or (os.stat(private).st_mode & 0o077) == 0
    key_ok = (pair_exists or pair_absent) and secure_mode
    if pair_exists and not secure_mode:
        key_detail = f"{private} permissions are too open; use chmod 600"
    elif pair_exists and shutil.which("ssh-keygen"):
        fingerprint = run(["ssh-keygen", "-lf", str(config.public_key)], timeout=10)
        key_ok = fingerprint.returncode == 0
        key_detail = (fingerprint.stdout or fingerprint.stderr).strip()
    elif pair_exists:
        key_ok = False
        key_detail = "cannot validate key without ssh-keygen"
    else:
        key_detail = "will be generated safely at launch"
    if not pair_exists and not pair_absent:
        key_detail = "incomplete key pair; no file will be overwritten"
    results.append(Diagnostic("SSH key", key_ok, key_detail))

    if not shutil.which("aws"):
        unavailable = "AWS CLI unavailable"
        results.extend(Diagnostic(name, False, unavailable) for name in
                       ("AWS authentication", "Region", "Default VPC", "Quota sanity",
                        "Existing Control Workstation"))
        return tuple(results)
    try:
        identity = aws(["sts", "get-caller-identity"], config)
        results.append(Diagnostic("AWS authentication", True, identity.get("Arn", "authenticated")))
    except AwsError as exc:
        results.append(Diagnostic("AWS authentication", False, str(exc).splitlines()[-1]))
        unavailable = "not checked because AWS authentication failed"
        results.extend(Diagnostic(name, False, unavailable) for name in
                       ("Region", "Default VPC", "Quota sanity", "Existing Control Workstation"))
        return tuple(results)
    try:
        aws(["ec2", "describe-regions", "--region-names", config.region], config)
        results.append(Diagnostic("Region", True, config.region))
    except AwsError as exc:
        results.append(Diagnostic("Region", False, str(exc).splitlines()[-1]))
    try:
        vpc, subnet = default_network(config)
        results.append(Diagnostic("Default VPC", True, f"{vpc} / {subnet}"))
    except AwsError as exc:
        results.append(Diagnostic("Default VPC", False, str(exc)))
    try:
        types = aws(["ec2", "describe-instance-types", "--instance-types", config.instance_type], config)
        required_vcpus = types["InstanceTypes"][0]["VCpuInfo"]["DefaultVCpus"]
        quotas = aws(["service-quotas", "get-service-quota", "--service-code", "ec2", "--quota-code", "L-1216C47A"], config)
        value = quotas.get("Quota", {}).get("Value", 0)
        detail = f"{value:g} standard On-Demand vCPUs; {config.instance_type} requires {required_vcpus}"
        results.append(Diagnostic("Quota sanity", value >= required_vcpus, detail))
    except (AwsError, IndexError, KeyError) as exc:
        results.append(Diagnostic("Quota sanity", False, str(exc).splitlines()[-1]))
    try:
        existing = find_instances(config)
        detail = f"{len(existing)} managed instance(s)" if existing else "none"
        results.append(Diagnostic("Existing Control Workstation", len(existing) <= 1, detail))
    except AwsError as exc:
        results.append(Diagnostic("Existing Control Workstation", False, str(exc)))
    return tuple(results)
