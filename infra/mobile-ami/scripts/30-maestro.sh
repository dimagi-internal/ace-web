#!/bin/bash
# Maestro CLI to /opt/maestro. Pinning to a 2.5.x release so the recipe
# semantics in the bake script match what's been verified on the laptop
# AVD.
set -euo pipefail

MAESTRO_VERSION="${MAESTRO_VERSION:-2.5.1}"
# Pin to 2.5.1 (latest stable as of 2026-05). The ACE plugin's
# mobile-integration playbook documents recipes verified against
# Maestro 2.3.0-2.5.1 (the dadb 1.2.10 line); pinning to 2.5.1 stays
# inside that verified window.
INSTALL_DIR=/opt/maestro

mkdir -p "$INSTALL_DIR"
cd /tmp

curl -fsSL "https://github.com/mobile-dev-inc/maestro/releases/download/cli-${MAESTRO_VERSION}/maestro.zip" \
  -o maestro.zip

unzip -q maestro.zip -d "$INSTALL_DIR"
rm -f maestro.zip

# Maestro distributes as `maestro/bin/maestro`; symlink for convenience.
ln -sf "$INSTALL_DIR/maestro/bin/maestro" /usr/local/bin/maestro

# Smoke test.
maestro --version | tee /var/log/maestro-version.log
