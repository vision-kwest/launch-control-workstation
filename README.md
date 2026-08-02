# launch-control-workstation

`launch-control-workstation` is a production-ready, feature-complete utility that provisions a persistent, lightweight Ubuntu EC2
machine for managing a studio's infrastructure. It is an IaC control node—not a
GPU, desktop, or artist workstation—and replaces the limited persistent storage
available in AWS CloudShell.

The utility uses Python's standard library and shells out to the AWS CLI. It does
not require OpenTofu or `boto3` on the machine doing the provisioning.

## Architecture

The launcher selects Canonical's current Ubuntu 24.04 LTS x86-64 gp3 AMI from
the public SSM parameter, then launches one instance in the default VPC and a
default subnet. The root volume is encrypted, tagged, and deleted on termination.
IMDSv2 is mandatory, detailed monitoring is enabled, and shutdown terminates the
instance. A managed security group permits SSH from `LCW_SSH_CIDR`.

Cloud-init embeds and executes `scripts/bootstrap.sh`, which installs a focused
toolset: Git, common shell utilities, build tools, Python, GitHub CLI, SSH, and
the latest stable OpenTofu package from its official apt repository. It does not
install Docker, graphics drivers, desktop software, or DCC tools.

## Requirements

* Python 3.12+
* AWS CLI v2 authenticated by the current CloudShell session (do not run
  `aws configure`) with permission to use EC2, IAM, S3, SSM, CloudWatch, STS,
  CodeBuild, EventBridge Scheduler, and read the EC2 Service Quotas API
* Git
* `ssh` and `ssh-keygen` (a default ED25519 key is created automatically when neither key file exists)
* A default VPC with at least one default subnet and an internet route

Run `workstation doctor` first. It performs read-only checks of local tools, AWS authentication, region networking, EC2 quota, SSH-key state, and existing managed workstations. It never modifies AWS resources.

## AWS Authentication

CloudShell authenticates the launcher with its existing temporary session. The
launcher creates a dedicated EC2 IAM role and instance profile, attaches that
profile when the Control Workstation is created, and requires IMDSv2. The
workstation's AWS CLI and OpenTofu automatically obtain rotating, temporary
credentials from EC2 Instance Metadata—no extra provider configuration is
needed.

No AWS credentials are copied to the workstation, no access keys are generated,
and no secrets or credential files are stored. This is safer than long-lived
user keys because credentials are short-lived, rotated by AWS, scoped to the
workload role, and unavailable through IMDS requests that omit a session token.

The role uses these AWS-managed policies initially:

| Managed policy | Purpose |
|---|---|
| `AmazonEC2FullAccess` | Provision and manage the studio EC2 fleet. |
| `IAMFullAccess` | Create and pass the workload roles required by studio provisioning; this is deliberately narrower than `AdministratorAccess`. |
| `AmazonS3FullAccess` | Access OpenTofu state backends and infrastructure artifacts. |
| `AmazonSSMFullAccess` | Resolve parameters and manage instances through Systems Manager. |
| `CloudWatchFullAccessV2` | Publish and manage studio metrics, logs, and alarms. |
| `AWSCodeBuildAdminAccess` | Create and operate the shared automatic-expiration project used by studio infrastructure. |

The role also has a least-privilege inline policy for automatic expiration. It
can manage only EventBridge Scheduler schedules named `studio-expiry-*` in the
configured region and account, and can pass only the
`studio-expiration-scheduler` role to `scheduler.amazonaws.com`. Rerun
`workstation launch` from the authorized CloudShell environment to reconcile
this policy onto an existing workstation role; do not configure static AWS
credentials on the workstation.

These policies are centralized in `iam.py`, where they can be replaced with
studio-specific customer-managed policies as the infrastructure permission set
stabilizes. `workstation doctor` uses IAM policy simulation to warn about missing
launcher permissions without creating or changing resources.

## Installation

### End users

The popular AWS CloudShell tool natively supports installing the 
package from PyPI into the current Python environment:

```bash
python3 -m pip install launch-control-workstation
```

The recommended installation uses [pipx](https://pipx.pypa.io/), 
which gives the command its own isolated Python environment 
while making it available on `PATH`:

```bash
python3 -m pip install pipx
pipx install launch-control-workstation
```

Then sanity check becomes.

```bash
workstation version
workstation doctor
```

GitHub is the source repository; PyPI is the official distribution channel.

Upgrade or remove a pipx installation with:

```bash
pipx upgrade launch-control-workstation
pipx uninstall launch-control-workstation
```

### Development

Clone the repository and create an editable installation:

```bash
git clone https://github.com/Vision-Kwest/launch-control-workstation.git
cd launch-control-workstation
python -m pip install -e .
workstation version
workstation doctor
```

Install the test and packaging tools when contributing:

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m build
python -m twine check dist/*
```

The project uses Hatchling because this is a pure-Python `src`-layout package
with no compiled extensions or custom build steps. Package metadata follows PEP
621 in `pyproject.toml`; the wheel includes the cloud-init template and bootstrap
script used at runtime.

## Launch

```bash
workstation launch
```

Launch is idempotent: it reuses a tagged active instance and starts it when it is
stopped. The first run creates (when necessary) and imports the configured key and
creates a tagged SSH security group. Existing keys are never overwritten, and the
local and EC2 key fingerprints must match. The launcher verifies SSH authentication,
waits across any cloud-init reboot, and checks every installed tool before declaring
the workstation ready. Add `--login` to open a session after verification; launch
does not log in by default.

## Why the Control Workstation exists

The Control Workstation separates the short-lived control plane from durable infrastructure operations. AWS CloudShell is ideal for authentication and launching, but its short idle timeout and constrained persistence make it a poor place for long-running stateful IaC workflows. OpenTofu is therefore intentionally installed and executed on the Control Workstation—not in CloudShell—where configuration, state access, logs, and operator sessions remain stable.

## Typical CloudShell, laptop, and VS Code workflows

Run `workstation doctor` and `workstation launch` from CloudShell, then use `workstation ssh` to continue there. Laptop users copy the printed `ssh -i ~/.ssh/id_ed25519 ubuntu@<public-ip>` command (after securely making the same private key available). VS Code users copy the printed `Host control-workstation` block into `~/.ssh/config` and select that host with Remote SSH.

## Typical Workflow

```text
AWS CloudShell
      ↓
   launch.py
      ↓
Control Workstation
      ↓
studio-infrastructure
      ↓
 GPU Workstations
```

CloudShell is an excellent zero-setup launch point, but its browser session has a
short idle timeout and limited persistent storage. Many users therefore leave it
immediately after provisioning and use the durable control workstation for their
daily infrastructure work.

Continue directly in CloudShell with `workstation ssh`, or copy the launcher's
printed command to another computer that has the same private key:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<public-ip>
```

The security group defaults to `0.0.0.0/0` for portability. Restrict
`LCW_SSH_CIDR` to your trusted public address (for example `203.0.113.10/32`) for
production use.

## Configuration

All options are environment variables, so no tracked source edits are needed.

| Variable | Default | Meaning |
|---|---|---|
| `LCW_REGION` | `us-east-1` | AWS region |
| `LCW_INSTANCE_TYPE` | `t3.large` | EC2 instance type |
| `LCW_DISK_SIZE` | `100` | root gp3 volume size in GiB |
| `LCW_OWNER` | local `$USER` | Owner tag |
| `LCW_PROJECT` | `StudioInfrastructure` | Project tag |
| `LCW_ENVIRONMENT` | `development` | Environment tag |
| `LCW_SSH_TIMEOUT` | `600` | port 22 timeout in seconds |
| `LCW_CLOUD_INIT_TIMEOUT` | `1800` | cloud-init completion timeout in seconds |
| `LCW_HEALTH_CHECK_TIMEOUT` | `60` | individual remote health-check timeout |
| `LCW_AUTO_LOGIN` | `false` | open SSH automatically after a healthy launch |
| `LCW_SSH_CIDR` | `0.0.0.0/0` | permitted source CIDR |
| `LCW_PUBLIC_KEY` | `~/.ssh/id_ed25519.pub` | public key to import |
| `LCW_KEY_NAME` | `launch-control-workstation` | EC2 key-pair name |
| `LCW_SECURITY_GROUP` | `launch-control-workstation` | security-group name |

Example: `LCW_OWNER=vfx-platform LCW_SSH_CIDR=203.0.113.10/32 workstation launch`.

## Status, SSH, and destroy

```bash
workstation status
workstation ssh
workstation destroy
```

`status.py` reports lifecycle and addressing details, verifies SSH and cloud-init,
and displays the OpenTofu, Git, GitHub CLI, and Python versions plus the bootstrap
completion time, instance-profile attachment, IMDS availability, temporary
credentials, STS identity, and an overall health summary. On the first SSH login, run
`gh auth login`; GitHub authentication is never performed automatically.

`workstation destroy` finds every managed workstation by tags, asks for confirmation,
terminates it, waits, and removes the now-unused instance profile and IAM role.
Automation can explicitly use `workstation destroy --yes`. The tagged security
group and imported EC2 key pair are retained for the next run.

## Troubleshooting

* **Launcher credentials fail:** refresh the CloudShell session, then verify
  `aws sts get-caller-identity`; never copy those credentials to the workstation.
* **Workstation credentials fail:** run `workstation status` and inspect the AWS
  section. Confirm the instance profile is attached and IMDSv2 is reachable;
  do not run `aws configure` or set static credential environment variables.
* **No default VPC/subnet:** recreate a default VPC or launch in a region where
  one exists.
* **SSH timeout:** verify the subnet route, network ACL, public IP, and
  `LCW_SSH_CIDR`. Confirm your local firewall permits outbound TCP/22.
* **Key mismatch:** if no managed workstation exists, launch warns and
  automatically replaces the stale EC2 registration with `LCW_PUBLIC_KEY`. The
  local private key is not changed. If a managed workstation still exists, the
  mismatch remains fatal; destroy it first or choose a new `LCW_KEY_NAME` so the
  launcher cannot accidentally make an existing workstation inaccessible.
  This is expected when returning in a fresh CloudShell: `workstation destroy`
  retains the EC2 key-pair registration, but a fresh CloudShell without the
  previous `~/.ssh/id_ed25519` generates a different key. Because the default
  `LCW_KEY_NAME` is reused in the same account and region, the launcher refuses
  to replace that registration while a managed instance exists. Preserve and
  restore the original SSH key, allow automatic replacement after destroying
  the instance, or set a unique `LCW_KEY_NAME` for each ephemeral environment.
* **Bootstrap failure:** SSH in and inspect `/var/log/cloud-init-output.log` and
  `/var/log/launch-control-bootstrap.log`.
* **Expiration bootstrap reports `codebuild:CreateProject` denied:** rerun
  `workstation launch` from an identity allowed to update the workstation role.
  Launch idempotently attaches `AWSCodeBuildAdminAccess`; existing workstations
  receive the added permission through their shared instance role without being
  recreated. Then retry the studio infrastructure launch command.

## Cost expectations

AWS charges for the EC2 instance, a 100 GiB gp3 volume, detailed monitoring, and
public IPv4 addressing; data transfer may also apply. Prices vary by region and
change over time, so consult the AWS pricing pages and stop or destroy unused
resources. A stopped instance still incurs EBS storage charges.

## Releases and publishing

Versions follow [Semantic Versioning](https://semver.org/). The sole version
source is `src/launch_control_workstation/version.py`; package metadata and the
`workstation version` command both read it dynamically. Release tags must match
that value exactly as `vX.Y.Z`.

Maintainers publish with this sequence—there are no manual uploads or manual
PyPI steps:

1. Update [CHANGELOG.md](CHANGELOG.md).
2. Update the authoritative version.
3. Commit those changes.
4. Create a matching tag, for example `git tag v1.1.0`.
5. Push the tag with `git push origin v1.1.0`.
6. GitHub Actions tests, lints, builds, and validates the distributions.
7. GitHub Trusted Publishing publishes them to PyPI.
8. The workflow creates the GitHub Release and uploads both artifacts.
9. A separate job installs the public PyPI release with pip and pipx and checks
   the installed CLI.

The Trusted Publisher is scoped to this repository, `.github/workflows/release.yml`,
and the `pypi` environment; no PyPI API token or repository secret is needed.
See [PyPI](https://pypi.org/project/launch-control-workstation/),
[GitHub Releases](https://github.com/Vision-Kwest/launch-control-workstation/releases),
and [CHANGELOG.md](CHANGELOG.md) for published history.

## License

MIT. See [LICENSE](LICENSE).
