#!/bin/bash
# Maestro CLI to /opt/maestro. Pinning to a 2.5.x release so the recipe
# semantics in the bake script match what's been verified on the laptop
# AVD.
set -euo pipefail

MAESTRO_VERSION="${MAESTRO_VERSION:-1.39.0}"
# NOTE: Maestro versioning swung back from "2.5.x" pre-releases to a
# stable 1.x line in 2025. Pin to 1.39 (latest as of 2026-05) — the
# CommCare recipes were verified against this release.
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
