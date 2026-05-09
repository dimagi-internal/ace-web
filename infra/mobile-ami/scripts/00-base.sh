#!/bin/bash
# Base packages: KVM, JDK 17 (required by Android cmdline-tools), and
# everything the later scripts assume is on PATH.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get upgrade -y

apt-get install -y --no-install-recommends \
  ca-certificates curl wget unzip jq \
  qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils \
  cpu-checker \
  openjdk-17-jdk-headless \
  python3 python3-pip \
  systemd-timesyncd \
  `# Headless Android emulator runtime deps. -no-window skips the GUI` \
  `# but swiftshader/vulkan still link X11 + GL libs, and the emulator` \
  `# segfaults at startup if any are missing (verified on 2026-05-09:` \
  `# 'Could not open libX11-xcb.so.1, give up' SIGSEGV).` \
  libx11-6 libx11-xcb1 libxext6 libxkbcommon0 \
  libgl1 libpulse0 libnss3

# AWS CLI v2 — Ubuntu 24.04's apt no longer carries `awscli`, so we
# install the official static bundle. Used at runtime by run_recipe to
# `aws s3 cp` artifacts up to the artifacts bucket from the instance.
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
rm -rf /tmp/aws /tmp/awscliv2.zip
aws --version | tee /var/log/awscli-version.log

# Confirm the bake instance actually exposes nested virt; KVM is required
# for the Android emulator to work without `-no-accel`. m8i.xlarge supports
# this; if you change instance_type and this fails, see README.
kvm-ok | tee /var/log/kvm-ok.log

# Make /dev/kvm group-readable and add the ubuntu user so the runtime
# emulator service can use it without root.
groupadd -f kvm
usermod -aG kvm,libvirt ubuntu

# /opt/ace is the canonical "stuff baked into this AMI" prefix.
mkdir -p /opt/ace /opt/ace/apks /opt/ace/recipes /var/log/ace-mobile

# /var/log/ace-mobile is written to by the emulator (running as ubuntu)
# and the idle-shutdown timer. Make it ubuntu-owned so redirects from
# the bake script and runtime service don't hit Permission denied.
chown ubuntu:ubuntu /var/log/ace-mobile

# Tmpfile config so /var/run/ace-mobile/ exists on every boot for the
# idle-marker file the SSM commands touch.
cat >/etc/tmpfiles.d/ace-mobile.conf <<'EOF'
d /var/run/ace-mobile 0755 ubuntu ubuntu -
EOF
systemd-tmpfiles --create /etc/tmpfiles.d/ace-mobile.conf
