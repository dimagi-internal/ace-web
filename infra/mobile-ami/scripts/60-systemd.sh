#!/bin/bash
# Install the runtime systemd units. Done after the snapshot bake so the
# runner doesn't try to start during provisioning.
set -euo pipefail

install -m 0644 /tmp/ace-mobile-runner.service   /etc/systemd/system/ace-mobile-runner.service
install -m 0644 /tmp/ace-idle-shutdown.service   /etc/systemd/system/ace-idle-shutdown.service
install -m 0644 /tmp/ace-idle-shutdown.timer     /etc/systemd/system/ace-idle-shutdown.timer
install -m 0755 /tmp/ace-idle-shutdown.sh        /usr/local/bin/ace-idle-shutdown

# sudoers entry: the idle script needs to call /sbin/shutdown without a
# password. Scoped to the exact command.
cat >/etc/sudoers.d/ace-idle-shutdown <<'EOF'
ubuntu ALL=(root) NOPASSWD: /sbin/shutdown -h now
EOF
chmod 0440 /etc/sudoers.d/ace-idle-shutdown

systemctl daemon-reload

# Enable but DO NOT start — they'll start on next boot (the AMI's first
# real boot, which is the EC2 instance launched by Terraform).
systemctl enable ace-mobile-runner.service
systemctl enable ace-idle-shutdown.timer
