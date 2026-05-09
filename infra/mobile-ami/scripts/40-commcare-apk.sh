#!/bin/bash
# CommCare 2.62.0 APK. Pinned because the connect-register recipes were
# verified against this exact build (see comment headers on the recipes).
# Bumping the APK requires re-verifying selectors.
set -euo pipefail

COMMCARE_VERSION="${COMMCARE_VERSION:-2.62.0}"
# GitHub Releases asset name: dimagi/commcare-android publishes the
# release APK as `app-commcare-release.apk` under the tag
# `commcare_${VERSION}`. Verified against 2.62.0 on 2026-05-09.
COMMCARE_APK_URL="${COMMCARE_APK_URL:-https://github.com/dimagi/commcare-android/releases/download/commcare_${COMMCARE_VERSION}/app-commcare-release.apk}"

APK_DIR=/opt/ace/apks
APK_PATH="$APK_DIR/commcare.apk"

mkdir -p "$APK_DIR"

curl -fsSL "$COMMCARE_APK_URL" -o "$APK_PATH"

# Record md5 so /api/mobile/status can surface a fingerprint without
# re-hashing on every status call.
md5sum "$APK_PATH" | awk '{print $1}' > "$APK_PATH.md5"

# Manifest of what's baked.
cat > /opt/ace/MANIFEST.txt <<EOF
commcare_apk_version=$COMMCARE_VERSION
commcare_apk_md5=$(cat "$APK_PATH.md5")
baked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

chown -R ubuntu:ubuntu /opt/ace
