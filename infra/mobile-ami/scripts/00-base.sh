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
  awscli \
  python3 python3-pip \
  systemd-timesyncd

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

# Tmpfile config so /var/run/ace-mobile/ exists on every boot for the
# idle-marker file the SSM commands touch.
cat >/etc/tmpfiles.d/ace-mobile.conf <<'EOF'
d /var/run/ace-mobile 0755 ubuntu ubuntu -
EOF
systemd-tmpfiles --create /etc/tmpfiles.d/ace-mobile.conf
