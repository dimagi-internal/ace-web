#!/bin/bash
# Install the Android SDK cmdline-tools, then use sdkmanager to fetch
# platform-tools, emulator, and the API 34 google_apis x86_64 system
# image. Lives entirely under /opt/android-sdk.
set -euo pipefail

ANDROID_SDK_ROOT=/opt/android-sdk
CMDLINE_TOOLS_VERSION=11076708 # Sept 2024 stable; matches Android Studio Hedgehog+
SYSTEM_IMAGE="system-images;android-34;google_apis;x86_64"

mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
cd /tmp

wget -q "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" -O cmdline-tools.zip
unzip -q cmdline-tools.zip
mv cmdline-tools "$ANDROID_SDK_ROOT/cmdline-tools/latest"
rm -f cmdline-tools.zip

cat >>/etc/profile.d/android-sdk.sh <<'EOF'
export ANDROID_SDK_ROOT=/opt/android-sdk
export ANDROID_HOME=/opt/android-sdk
export PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator
EOF
chmod 0644 /etc/profile.d/android-sdk.sh
# shellcheck disable=SC1091
source /etc/profile.d/android-sdk.sh

# Accept all licenses up-front (otherwise sdkmanager prompts). `yes`
# gets SIGPIPE'd (exit 141) when sdkmanager closes its stdin after
# the last license is accepted; with set -o pipefail that aborts the
# script. Disable pipefail for this one command — the only exit code
# we care about is sdkmanager's.
set +o pipefail
yes | sdkmanager --licenses >/dev/null
set -o pipefail

sdkmanager \
  "platform-tools" \
  "emulator" \
  "platforms;android-34" \
  "$SYSTEM_IMAGE"

# Make the SDK readable by the ubuntu user so the runner service doesn't
# need root.
chown -R ubuntu:ubuntu "$ANDROID_SDK_ROOT"
