"""IAM instance-role lifecycle for the Control Workstation."""

from __future__ import annotations

from dataclasses import dataclass

from .aws import AwsError, aws
from .config import Config

ROLE_NAME = "launch-control-workstation"
PROFILE_NAME = "launch-control-workstation"

# EC2 operations are the workstation's primary purpose, including provisioning
# and managing the studio's compute fleet.
MANAGED_POLICIES = {
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess": "manage studio EC2 resources",
    # Studio provisioning creates and passes workload roles. IAMFullAccess is
    # intentionally used instead of AdministratorAccess and can later be
    # replaced by a studio-specific customer-managed boundary policy.
    "arn:aws:iam::aws:policy/IAMFullAccess": "provision workload IAM roles and instance profiles",
    # OpenTofu state and artifacts live in S3; no local static credentials are used.
    "arn:aws:iam::aws:policy/AmazonS3FullAccess": "read and write OpenTofu backends",
    # SSM supplies public AMI parameters and manages studio instances.
    "arn:aws:iam::aws:policy/AmazonSSMFullAccess": "read parameters and manage instances with SSM",
    # Infrastructure workflows publish and inspect operational metrics and logs.
    "arn:aws:iam::aws:policy/CloudWatchFullAccessV2": "manage CloudWatch telemetry",
}


@dataclass(frozen=True)
class ProfileState:
    """Describe the role and instance profile ensured by the launcher."""

    role_name: str
    profile_name: str


def ensure(config: Config) -> ProfileState:
    """Create or validate the EC2 role/profile and attach documented policies."""
    try:
        aws(["iam", "get-role", "--role-name", ROLE_NAME], config)
    except AwsError:
        trust = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
        aws(["iam", "create-role", "--role-name", ROLE_NAME,
             "--assume-role-policy-document", trust,
             "--description", "Temporary AWS credentials for the Control Workstation"], config)
    for policy_arn in MANAGED_POLICIES:
        aws(["iam", "attach-role-policy", "--role-name", ROLE_NAME,
             "--policy-arn", policy_arn], config)
    try:
        profile = aws(["iam", "get-instance-profile", "--instance-profile-name", PROFILE_NAME], config)
    except AwsError:
        profile = aws(["iam", "create-instance-profile", "--instance-profile-name", PROFILE_NAME], config)
    roles = profile.get("InstanceProfile", {}).get("Roles", [])
    foreign_roles = [role.get("RoleName", "unknown") for role in roles
                     if role.get("RoleName") != ROLE_NAME]
    if foreign_roles:
        raise AwsError(f"Instance profile {PROFILE_NAME} is owned by another role: {', '.join(foreign_roles)}")
    if not any(role.get("RoleName") == ROLE_NAME for role in roles):
        aws(["iam", "add-role-to-instance-profile", "--instance-profile-name", PROFILE_NAME,
             "--role-name", ROLE_NAME], config)
    state = ProfileState(ROLE_NAME, PROFILE_NAME)
    validate(config)
    return state


def validate(config: Config) -> None:
    """Require the managed role to trust EC2 and contain every declared policy."""
    role = aws(["iam", "get-role", "--role-name", ROLE_NAME], config).get("Role", {})
    statements = role.get("AssumeRolePolicyDocument", {}).get("Statement", [])
    trusts_ec2 = any(
        statement.get("Effect") == "Allow"
        and statement.get("Principal", {}).get("Service") == "ec2.amazonaws.com"
        and statement.get("Action") == "sts:AssumeRole"
        for statement in statements
    )
    if not trusts_ec2:
        raise AwsError(f"IAM role {ROLE_NAME} exists but does not trust EC2")
    attached = aws(["iam", "list-attached-role-policies", "--role-name", ROLE_NAME], config)
    policy_arns = {item.get("PolicyArn") for item in attached.get("AttachedPolicies", [])}
    missing = set(MANAGED_POLICIES) - policy_arns
    if missing:
        raise AwsError(f"IAM role {ROLE_NAME} is missing policies: {', '.join(sorted(missing))}")


def attach(instance_id: str, config: Config) -> None:
    """Associate the managed instance profile with an existing EC2 instance."""
    data = aws(["ec2", "describe-iam-instance-profile-associations", "--filters",
                f"Name=instance-id,Values={instance_id}", "Name=state,Values=associating,associated"], config)
    associations = data.get("IamInstanceProfileAssociations", [])
    if associations:
        arn = associations[0].get("IamInstanceProfile", {}).get("Arn", "")
        if arn.rsplit("/", 1)[-1] != PROFILE_NAME:
            aws(["ec2", "replace-iam-instance-profile-association", "--association-id",
                 associations[0]["AssociationId"], "--iam-instance-profile", f"Name={PROFILE_NAME}"], config)
    else:
        aws(["ec2", "associate-iam-instance-profile", "--instance-id", instance_id,
             "--iam-instance-profile", f"Name={PROFILE_NAME}"], config)


def cleanup(config: Config) -> bool:
    """Remove the profile and role only when no EC2 association still uses them."""
    associations = aws(["ec2", "describe-iam-instance-profile-associations", "--filters",
                        "Name=state,Values=associating,associated"], config)
    for association in associations.get("IamInstanceProfileAssociations", []):
        arn = association.get("IamInstanceProfile", {}).get("Arn", "")
        if arn.rsplit("/", 1)[-1] == PROFILE_NAME:
            return False
    try:
        aws(["iam", "remove-role-from-instance-profile", "--instance-profile-name", PROFILE_NAME,
             "--role-name", ROLE_NAME], config)
        aws(["iam", "delete-instance-profile", "--instance-profile-name", PROFILE_NAME], config)
        for policy_arn in MANAGED_POLICIES:
            aws(["iam", "detach-role-policy", "--role-name", ROLE_NAME,
                 "--policy-arn", policy_arn], config)
        aws(["iam", "delete-role", "--role-name", ROLE_NAME], config)
        return True
    except AwsError as exc:
        if "NoSuchEntity" in str(exc):
            return True
        raise


def required_actions() -> tuple[str, ...]:
    """Return launcher permissions used by read-only doctor policy simulation."""
    return ("iam:CreateRole", "iam:AttachRolePolicy", "iam:CreateInstanceProfile",
            "iam:AddRoleToInstanceProfile", "iam:PassRole",
            "ec2:AssociateIamInstanceProfile", "ec2:ReplaceIamInstanceProfileAssociation")
