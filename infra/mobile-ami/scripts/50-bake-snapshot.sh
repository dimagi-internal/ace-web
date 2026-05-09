#!/bin/bash
# Boot the AVD, install CommCare, register the +7426 demo user via the
# two Maestro recipes (no human OTP entry required — Connect-id
# short-circuits SMS for that prefix), save a snapshot named
# `registered-test-user`, and tear the emulator down.
#
# Required env vars (passed in by Packer from operator's environment;
# Packer renders them via `-var=...` in the .pkr.hcl):
#   TEST_PHONE_LOCAL  TEST_COUNTRY_CODE  TEST_PIN  TEST_BACKUP_CODE  TEST_NAME
set -euo pipefail

: "${TEST_PHONE_LOCAL:?TEST_PHONE_LOCAL is required}"
: "${TEST_COUNTRY_CODE:?TEST_COUNTRY_CODE is required}"
: "${TEST_PIN:?TEST_PIN is required}"
: "${TEST_BACKUP_CODE:?TEST_BACKUP_CODE is required}"
TEST_NAME="${TEST_NAME:-ACE Test User}"

# Sanity-check the +7426 demo prefix. The country code (typically "+7")
# and the local number (starting "426...") are split because the recipe
# types them into separate fields in CommCare. Connect-id's demo-bypass
# matches against the *concatenated* number, so we check the full thing.
combined="${TEST_COUNTRY_CODE}${TEST_PHONE_LOCAL}"
case "$combined" in
  +7426*) ;;
  *)
    echo "ERROR: combined phone '$combined' is not in the +7426 demo range." >&2
    echo "  Expected COUNTRY_CODE+PHONE_LOCAL to start with '+7426'. The" >&2
    echo "  bake only works with Connect-id's demo-bypass range — any" >&2
    echo "  other number requires real OTP delivery, which the bake" >&2
    echo "  can't intercept. See connect-register-to-otp.yaml header." >&2
    exit 1
    ;;
esac

ANDROID_SDK_ROOT=/opt/android-sdk
export ANDROID_SDK_ROOT
export ANDROID_HOME=/opt/android-sdk
export PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:/usr/local/bin

AVD_NAME=ACE_Pixel_API_34
APK_PATH=/opt/ace/apks/commcare.apk
RECIPE_DIR=/opt/ace/recipes
SNAPSHOT_NAME=registered-test-user

# Recipes were staged by Packer's `file` provisioner to /tmp/recipes/.
# Move them into /opt/ace/recipes so the runtime service can find them.
mkdir -p "$RECIPE_DIR"
cp -v /tmp/recipes/*.yaml "$RECIPE_DIR/"
chown -R ubuntu:ubuntu "$RECIPE_DIR"

# Boot the emulator headless. Run as ubuntu (KVM group membership set
# in 00-base.sh).
sudo -u ubuntu -E bash <<EOF_INNER
set -euo pipefail
export ANDROID_SDK_ROOT=/opt/android-sdk
export ANDROID_HOME=/opt/android-sdk
export PATH=\$PATH:\$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:\$ANDROID_SDK_ROOT/platform-tools:\$ANDROID_SDK_ROOT/emulator:/usr/local/bin

# Start emulator in background. -no-snapshot-save means we won't accidentally
# overwrite the default-boot snapshot; we save the named one explicitly below.
nohup emulator -avd $AVD_NAME \
  -no-window -no-audio \
  -gpu swiftshader_indirect \
  -no-snapshot-save \
  -no-boot-anim \
  > /var/log/ace-mobile/bake-emulator.log 2>&1 &

# Wait for boot.
echo "Waiting for adb to see the emulator..."
adb wait-for-device

echo "Waiting for sys.boot_completed..."
boot_complete=""
for i in \$(seq 1 60); do
  boot_complete=\$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  if [[ "\$boot_complete" == "1" ]]; then
    break
  fi
  sleep 5
done
if [[ "\$boot_complete" != "1" ]]; then
  echo "Boot timed out" >&2
  exit 1
fi

# Disable GMS so MicroImageActivity falls back to ManualMode (see
# comment header in connect-register-from-otp.yaml).
adb shell pm disable-user --user 0 com.google.android.gms || true

# Install CommCare.
adb install -r $APK_PATH

# Pre-grant CAMERA so MicroImageActivity doesn't bail.
adb shell pm grant org.commcare.dalvik android.permission.CAMERA || true

# Run the two registration recipes.
cd $RECIPE_DIR
maestro test connect-register-to-otp.yaml \
  --env COUNTRY_CODE='$TEST_COUNTRY_CODE' \
  --env PHONE_LOCAL='$TEST_PHONE_LOCAL' \
  --env PHONE='${TEST_COUNTRY_CODE}${TEST_PHONE_LOCAL}'

maestro test connect-register-from-otp.yaml \
  --env NAME='$TEST_NAME' \
  --env BACKUP_CODE='$TEST_BACKUP_CODE' \
  --env PIN='$TEST_PIN'

# Save snapshot.
adb emu avd snapshot save $SNAPSHOT_NAME

# Confirm snapshot exists before killing.
adb emu avd snapshot list

# Clean shutdown.
adb emu kill
EOF_INNER

# Wait for emulator process to actually exit.
for i in $(seq 1 30); do
  if ! pgrep -f "emulator -avd $AVD_NAME" >/dev/null; then
    break
  fi
  sleep 1
done

echo "Snapshot bake complete."
