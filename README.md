# launch-control-workstation

`launch-control-workstation` **v1.0.0** is a production-ready, feature-complete utility that provisions a persistent, lightweight Ubuntu EC2
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

* Python 3.10+
* AWS CLI v2 configured with credentials and permission to use EC2, SSM, STS,
  and read the EC2 Service Quotas API
* Git
* `ssh` and `ssh-keygen` (a default ED25519 key is created automatically when neither key file exists)
* A default VPC with at least one default subnet and an internet route

Run `./workstation doctor` first. It performs read-only checks of local tools, AWS authentication, region networking, EC2 quota, SSH-key state, and existing managed workstations. It never modifies AWS resources.

## Launch

```bash
git clone <repository-url>
cd launch-control-workstation
./workstation launch
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

Run `./workstation doctor` and `./workstation launch` from CloudShell, then use `./workstation ssh` to continue there. Laptop users copy the printed `ssh -i ~/.ssh/id_ed25519 ubuntu@<public-ip>` command (after securely making the same private key available). VS Code users copy the printed `Host control-workstation` block into `~/.ssh/config` and select that host with Remote SSH.

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

Continue directly in CloudShell with `./workstation ssh`, or copy the launcher's
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

Example: `LCW_OWNER=vfx-platform LCW_SSH_CIDR=203.0.113.10/32 ./workstation launch`.

## Status, SSH, and destroy

```bash
./workstation status
./workstation ssh
./workstation destroy
```

`status.py` reports lifecycle and addressing details, verifies SSH and cloud-init,
and displays the OpenTofu, Git, GitHub CLI, and Python versions plus the bootstrap
completion time and an overall health summary. On the first SSH login, run
`gh auth login`; GitHub authentication is never performed automatically.

`workstation destroy` finds every managed workstation by tags, asks for confirmation,
terminates it, and waits. Automation can explicitly use `./workstation destroy --yes`.
The tagged security group and imported EC2 key pair are retained for the next run.

## Troubleshooting

* **Credentials fail:** rerun `aws configure`, AWS SSO login, or refresh the
  CloudShell session, then verify `aws sts get-caller-identity`.
* **No default VPC/subnet:** recreate a default VPC or launch in a region where
  one exists.
* **SSH timeout:** verify the subnet route, network ACL, public IP, and
  `LCW_SSH_CIDR`. Confirm your local firewall permits outbound TCP/22.
* **Key mismatch:** if no managed workstation exists, run
  `./workstation launch --replace-key-pair` to replace the stale EC2 registration
  with `LCW_PUBLIC_KEY`. The local private key is not changed. If a managed
  workstation still exists, destroy it first or choose a new `LCW_KEY_NAME` so
  the launcher cannot accidentally make an existing workstation inaccessible.
* **Bootstrap failure:** SSH in and inspect `/var/log/cloud-init-output.log` and
  `/var/log/launch-control-bootstrap.log`.

## Cost expectations

AWS charges for the EC2 instance, a 100 GiB gp3 volume, detailed monitoring, and
public IPv4 addressing; data transfer may also apply. Prices vary by region and
change over time, so consult the AWS pricing pages and stop or destroy unused
resources. A stopped instance still incurs EBS storage charges.

## Release status

Version 1.0.0 is feature complete. Future development is limited to bug fixes and maintenance. See [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
