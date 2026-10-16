#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu server: updates, Docker, a firewall that allows only SSH,
# fail2ban, automatic security updates, a little swap, and key-only SSH. Run as root, and only
# after your SSH public key is in /root/.ssh/authorized_keys (it refuses to turn passwords off
# otherwise, so it cannot lock you out). Safe to run again.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y upgrade
apt-get -y install ca-certificates curl gnupg git jq ufw fail2ban unattended-upgrades

# Docker from Docker's own apt repository.
if ! command -v docker > /dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# The pipeline only makes outbound calls, so SSH is the only thing that should answer.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

# Swap, so a memory spike slows the box instead of killing a container.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Key-only SSH. The file name sorts first because sshd uses the first value it reads, and
# cloud images ship a drop-in that turns passwords on.
if [ -s /root/.ssh/authorized_keys ]; then
  cat > /etc/ssh/sshd_config.d/00-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  sshd -t
  systemctl reload ssh 2> /dev/null || systemctl reload sshd
  echo "SSH is now key-only."
else
  echo "No key in /root/.ssh/authorized_keys: leaving password login on." >&2
fi

docker --version
docker compose version
