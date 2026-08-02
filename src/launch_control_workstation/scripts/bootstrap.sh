#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a /var/log/launch-control-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl wget build-essential python3 python3-pip pipx unzip zip jq tree tmux htop openssh-server ca-certificates gnupg

# Install AWS CLI v2 system-wide. It discovers temporary instance-role
# credentials through IMDSv2; no credential file or access key is created.
machine="$(uname -m)"
case "$machine" in
  x86_64) aws_arch=x86_64 ;;
  aarch64) aws_arch=aarch64 ;;
  *) echo "Unsupported AWS CLI architecture: $machine" >&2; exit 1 ;;
esac
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install --update
aws --version

# Keep the application isolated from the system interpreter.  Ubuntu's pipx
# package is preferred, but ensurepath is still run so upgrades from older
# images retain a usable pipx installation.
pipx ensurepath
export PIPX_HOME=/opt/pipx
export PIPX_BIN_DIR=/usr/local/bin
export PATH="${PIPX_BIN_DIR}:${PATH}"
pipx --version

# Install a source revision known to implement the launcher's bootstrap
# contract. PyPI can lag behind the launcher, so accepting its latest release
# could leave bootstrap without commands that the launcher already relies on.
expected_cli_version=__LCW_VERSION__
cli_source_revision=b14869cadf1db6b704c5e7661c8ac26ae3ab7f7f
cli_install_source="git+https://github.com/Vision-Kwest/launch-control-workstation.git@${cli_source_revision}"
pipx install --force "$cli_install_source"

# A missing, broken, or unexpectedly-versioned CLI must stop cloud-init before
# any launcher-dependent commands are invoked.
installed_cli_version="$(workstation version)"
if [ "$installed_cli_version" != "$expected_cli_version" ]; then
  echo "Bootstrap CLI version mismatch: expected ${expected_cli_version}, installed ${installed_cli_version}" >&2
  exit 1
fi

# The durable control node, not the ephemeral launcher, owns the studio SSH
# identity. Run as the login user so the files live on its persistent root disk.
install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/.ssh
bootstrap_region=__LCW_REGION__
studio_key_name=__LCW_KEY_NAME__
runuser -u ubuntu -- env HOME=/home/ubuntu LCW_REGION="$bootstrap_region" \
  LCW_KEY_NAME="$studio_key_name" workstation key

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list

curl -fsSL https://get.opentofu.org/opentofu.gpg -o /etc/apt/keyrings/opentofu.gpg
curl -fsSL https://packages.opentofu.org/opentofu/tofu/gpgkey -o /tmp/opentofu-repo.gpg
gpg --no-default-keyring --keyring /tmp/opentofu-keyring.gpg --import /tmp/opentofu-repo.gpg
gpg --no-default-keyring --keyring /tmp/opentofu-keyring.gpg --export > /etc/apt/keyrings/opentofu-repo.gpg
echo "deb [signed-by=/etc/apt/keyrings/opentofu.gpg,/etc/apt/keyrings/opentofu-repo.gpg] https://packages.opentofu.org/opentofu/tofu/any/ any main" > /etc/apt/sources.list.d/opentofu.list

apt-get update
apt-get install -y gh tofu
systemctl enable --now ssh
tofu version
gh --version
install -d -m 0755 /var/lib/launch-control-workstation
date --iso-8601=seconds > /var/lib/launch-control-workstation/bootstrap-completed
runuser -u ubuntu -- env HOME=/home/ubuntu LCW_REGION="$bootstrap_region" \
  LCW_KEY_NAME="$studio_key_name" workstation doctor
echo "Bootstrap complete. After first login, run: gh auth login"
