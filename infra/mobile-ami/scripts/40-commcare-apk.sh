#!/bin/bash
# Download one or more CommCare APK versions into the AMI. Each version
# lands at /opt/ace/apks/<version>/commcare.apk and the bake script in
# step 50 turns each into a named snapshot (cc-<version>-registered).
#
# Multi-version is gated by the COMMCARE_VERSIONS env var, set by Packer
# from var.commcare_versions. Comma-separated list, e.g. "2.62.0" or
# "2.62.0,2.63.0,2.64.0". Single value still works.
#
# COMMCARE_APK_URL_TEMPLATE lets the operator override the GitHub
# Releases URL pattern if the asset naming changes upstream. Default:
# https://github.com/dimagi/commcare-android/releases/download/commcare_<VER>/app-commcare-release.apk
set -euo pipefail

COMMCARE_VERSIONS="${COMMCARE_VERSIONS:-2.63.0,2.62.0}"
URL_TEMPLATE="${COMMCARE_APK_URL_TEMPLATE:-https://github.com/dimagi/commcare-android/releases/download/commcare_<VER>/app-commcare-release.apk}"

APK_ROOT=/opt/ace/apks
mkdir -p "$APK_ROOT"

# Build (and update) /opt/ace/MANIFEST.txt as we go.
MANIFEST=/opt/ace/MANIFEST.txt
{
  echo "baked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commcare_versions=$COMMCARE_VERSIONS"
} > "$MANIFEST"

IFS=',' read -ra VERSIONS <<< "$COMMCARE_VERSIONS"
for VERSION in "${VERSIONS[@]}"; do
  VERSION="$(echo "$VERSION" | tr -d ' ')"
  APK_DIR="$APK_ROOT/$VERSION"
  APK_PATH="$APK_DIR/commcare.apk"
  URL="${URL_TEMPLATE//<VER>/$VERSION}"

  echo "=== CommCare $VERSION ==="
  echo "  url=$URL"
  echo "  path=$APK_PATH"

  mkdir -p "$APK_DIR"
  curl -fsSL "$URL" -o "$APK_PATH"
  MD5="$(md5sum "$APK_PATH" | awk '{print $1}')"
  echo "$MD5" > "$APK_PATH.md5"
  echo "  md5=$MD5"

  echo "commcare_${VERSION}_md5=$MD5" >> "$MANIFEST"
done

chown -R ubuntu:ubuntu /opt/ace

echo "=== /opt/ace/apks tree ==="
find "$APK_ROOT" -maxdepth 2 -type f | sort
echo "=== MANIFEST ==="
cat "$MANIFEST"
