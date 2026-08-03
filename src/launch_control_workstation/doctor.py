"""Read-only preflight diagnostics shared by doctor.py and launch.py."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from .aws import AwsError, aws, default_network, find_instances, ssh_fingerprints_match
from .config import Config
from .iam import required_actions
from .process import run


@dataclass(frozen=True)
class Diagnostic:
    """One prerequisite result; warnings are informative and do not block launch."""

    name: str
    passed: bool
    detail: str
    warning: bool = False


def _principal_arn(identity: dict[str, object]) -> str:
    """Convert an STS assumed-role ARN into the IAM role ARN simulation accepts."""
    arn = str(identity.get("Arn", ""))
    if ":assumed-role/" not in arn:
        return arn
    prefix, suffix = arn.split(":assumed-role/", 1)
    return f"{prefix.replace(':sts:', ':iam:')}:role/{suffix.split('/', 1)[0]}"


def _iam_permission_diagnostics(identity: dict[str, object], config: Config) -> tuple[Diagnostic, ...]:
    """Simulate required IAM/profile actions without changing any AWS resource."""
    actions = required_actions()
    try:
        data = aws(["iam", "simulate-principal-policy", "--policy-source-arn", _principal_arn(identity),
                    "--action-names", *actions], config)
        decisions = {item["EvalActionName"]: item["EvalDecision"]
                     for item in data.get("EvaluationResults", [])}
        iam_actions = tuple(action for action in actions if action.startswith("iam:"))
        ec2_actions = tuple(action for action in actions if action.startswith("ec2:"))
        iam_ok = all(decisions.get(action) == "allowed" for action in iam_actions)
        ec2_ok = all(decisions.get(action) == "allowed" for action in ec2_actions)
        return (
            Diagnostic("Create IAM resources", iam_ok,
                       "allowed" if iam_ok else "missing: " + ", ".join(a for a in iam_actions if decisions.get(a) != "allowed"), not iam_ok),
            Diagnostic("Attach instance profiles", ec2_ok,
                       "allowed" if ec2_ok else "missing: " + ", ".join(a for a in ec2_actions if decisions.get(a) != "allowed"), not ec2_ok),
        )
    except AwsError as exc:
        detail = "could not simulate current identity: " + str(exc).splitlines()[-1]
        return (Diagnostic("Create IAM resources", False, detail, True),
                Diagnostic("Attach instance profiles", False, detail, True))


def _identity_diagnostics(config: Config) -> tuple[Diagnostic, ...]:
    """Validate the workstation-owned key files and EC2 registration."""
    private = config.public_key.with_suffix("")
    private_ok = private.is_file()
    public_ok = config.public_key.is_file()
    results = [
        Diagnostic("Private key exists", private_ok, str(private)),
        Diagnostic("Public key exists", public_ok, str(config.public_key)),
    ]
    local = ""
    if public_ok and shutil.which("ssh-keygen"):
        fingerprint = run(["ssh-keygen", "-lf", str(config.public_key)], timeout=10)
        if fingerprint.returncode == 0:
            local = fingerprint.stdout.split()[1]
    try:
        pairs = aws(["ec2", "describe-key-pairs", "--key-names", config.key_name], config)["KeyPairs"]
    except AwsError as exc:
        results.extend((Diagnostic("EC2 key registered", False, str(exc).splitlines()[-1]),
                        Diagnostic("SSH fingerprints match", False, "registration unavailable")))
        return tuple(results)
    registered = bool(pairs)
    remote = pairs[0].get("KeyFingerprint", "") if registered else ""
    try:
        matches = ssh_fingerprints_match(local, remote)
    except ValueError:
        matches = False
    results.append(Diagnostic("EC2 key registered", registered, config.key_name))
    results.append(Diagnostic("SSH fingerprints match", matches,
                              f"local={local or 'unavailable'}, EC2={remote or 'unavailable'}"))
    return tuple(results)


def diagnose(config: Config, *, workstation_identity: bool = False) -> tuple[Diagnostic, ...]:
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
                       ("AWS authentication", "Current CloudShell credentials",
                        "Create IAM resources", "Attach instance profiles",
                        "Region", "Default VPC", "Quota sanity",
                        "Existing Control Workstation"))
        return tuple(results)
    try:
        identity = aws(["sts", "get-caller-identity"], config)
        results.append(Diagnostic("AWS authentication", True, identity.get("Arn", "authenticated")))
        results.append(Diagnostic("Current CloudShell credentials", True, identity.get("Arn", "authenticated")))
        results.extend(_iam_permission_diagnostics(identity, config))
    except AwsError as exc:
        results.append(Diagnostic("AWS authentication", False, str(exc).splitlines()[-1]))
        unavailable = "not checked because AWS authentication failed"
        results.extend(Diagnostic(name, False, unavailable) for name in
                       ("Current CloudShell credentials", "Create IAM resources",
                        "Attach instance profiles", "Region", "Default VPC",
                        "Quota sanity", "Existing Control Workstation"))
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
    if workstation_identity:
        results.extend(_identity_diagnostics(config))
    return tuple(results)
