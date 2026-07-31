#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a /var/log/launch-control-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl wget build-essential python3 python3-pip unzip zip jq tree tmux htop openssh-server ca-certificates gnupg

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
echo "Bootstrap complete. After first login, run: gh auth login"
