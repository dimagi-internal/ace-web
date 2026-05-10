#!/bin/bash
# Create the ACE_Pixel_API_34 AVD. The matching AVD on developer laptops
# is `ACE_Pixel_API_34` from the ACE plugin's mobile-bootstrap; we mirror
# the name exactly so recipes work the same on cloud and local.
set -euo pipefail

ANDROID_SDK_ROOT=/opt/android-sdk
export ANDROID_SDK_ROOT
export ANDROID_HOME=/opt/android-sdk
export PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator

AVD_HOME=/home/ubuntu/.android/avd
AVD_NAME=ACE_Pixel_API_34
SYSTEM_IMAGE="system-images;android-34;google_apis;x86_64"
DEVICE_PROFILE="pixel_7"

mkdir -p "$AVD_HOME"
chown -R ubuntu:ubuntu /home/ubuntu/.android

# avdmanager runs as ubuntu so file ownership lands right.
sudo -u ubuntu -E bash -lc "
  set -euo pipefail
  source /etc/profile.d/android-sdk.sh
  echo no | avdmanager create avd \
    --name '$AVD_NAME' \
    --package '$SYSTEM_IMAGE' \
    --device '$DEVICE_PROFILE' \
    --force
"

AVD_DIR="$AVD_HOME/${AVD_NAME}.avd"
CONFIG="$AVD_DIR/config.ini"

if [[ ! -f "$CONFIG" ]]; then
  echo "AVD config.ini not found at $CONFIG" >&2
  exit 1
fi

# Patch the AVD config:
#   - hw.camera.front=emulated  (so MicroImageActivity can fall back to
#     ManualMode after GMS is disabled)
#   - hw.ramSize=4096           (4 GB RAM — emulator is tight on 2 GB)
#   - disk.dataPartition.size=6G
patch_kv () {
  local key=$1 value=$2
  if grep -q "^${key}=" "$CONFIG"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$CONFIG"
  else
    echo "${key}=${value}" >> "$CONFIG"
  fi
}

patch_kv "hw.camera.front"        "emulated"
patch_kv "hw.camera.back"         "emulated"
patch_kv "hw.ramSize"             "4096"
patch_kv "disk.dataPartition.size" "6G"
patch_kv "hw.gpu.enabled"         "yes"
patch_kv "hw.gpu.mode"            "swiftshader_indirect"

chown -R ubuntu:ubuntu "$AVD_HOME"
