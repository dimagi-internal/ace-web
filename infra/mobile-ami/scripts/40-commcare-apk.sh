#!/bin/bash
# Download one or more CommCare APK versions into the AMI. Each version
# lands at /opt/ace/apks/<version>/commcare.apk and the bake script in
# step 50 turns each into a named snapshot (cc-<version>-registered).
#
# Multi-version is gated by the COMMCARE_VERSIONS env var, set by Packer
# from var.commcare_versions. Comma-separated list, e.g. "2.62.0" or
# "2.62.0,2.63.0,2.64.0". Single value still works.
#
# Dimagi changed the release asset filename in 2.63.0:
#   2.62.0 and earlier: app-commcare-release.apk
#   2.63.0 and later:   commcare-<VER>-release.apk
# We try the new pattern first, then fall back to the legacy pattern, so a
# single bake handles both old and new releases without per-version config.
# COMMCARE_APK_URL_TEMPLATES overrides the pattern list (comma-separated).
set -euo pipefail

COMMCARE_VERSIONS="${COMMCARE_VERSIONS:-2.63.0,2.62.0}"
URL_TEMPLATES_DEFAULT="https://github.com/dimagi/commcare-android/releases/download/commcare_<VER>/commcare-<VER>-release.apk,https://github.com/dimagi/commcare-android/releases/download/commcare_<VER>/app-commcare-release.apk"
URL_TEMPLATES="${COMMCARE_APK_URL_TEMPLATES:-$URL_TEMPLATES_DEFAULT}"

APK_ROOT=/opt/ace/apks
mkdir -p "$APK_ROOT"

# Build (and update) /opt/ace/MANIFEST.txt as we go.
MANIFEST=/opt/ace/MANIFEST.txt
{
  echo "baked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commcare_versions=$COMMCARE_VERSIONS"
} > "$MANIFEST"

IFS=',' read -ra VERSIONS <<< "$COMMCARE_VERSIONS"
IFS=',' read -ra TEMPLATES <<< "$URL_TEMPLATES"
for VERSION in "${VERSIONS[@]}"; do
  VERSION="$(echo "$VERSION" | tr -d ' ')"
  APK_DIR="$APK_ROOT/$VERSION"
  APK_PATH="$APK_DIR/commcare.apk"

  echo "=== CommCare $VERSION ==="
  echo "  path=$APK_PATH"
  mkdir -p "$APK_DIR"

  downloaded=0
  for TEMPLATE in "${TEMPLATES[@]}"; do
    URL="${TEMPLATE//<VER>/$VERSION}"
    echo "  trying url=$URL"
    if curl -fsSL "$URL" -o "$APK_PATH"; then
      downloaded=1
      echo "  ok: $URL"
      break
    fi
  done
  [[ $downloaded -eq 1 ]] || { echo "ERROR: no URL template matched for $VERSION" >&2; exit 22; }

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
