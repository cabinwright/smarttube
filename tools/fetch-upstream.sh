#!/bin/bash
# Download the pinned SmartTube armeabi-v7a APK and check its SHA-256.
# Based on gen5-SmartTube's tool of the same name.
# Prints the path of the verified APK (under .cache/upstream/).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/smarttube.conf"
OUT=$HERE/.cache/upstream
mkdir -p "$OUT"
apk=$OUT/$UPSTREAM_APK
url=https://github.com/$UPSTREAM_REPO/releases/download/$UPSTREAM_TAG/$UPSTREAM_APK

if [ ! -f "$apk" ] || [ "$(shasum -a 256 "$apk" | cut -d' ' -f1)" != "$UPSTREAM_SHA256" ]; then
    echo "downloading $url" >&2
    curl -fL --progress-bar -o "$apk.part" "$url"
    mv "$apk.part" "$apk"
fi
got=$(shasum -a 256 "$apk" | cut -d' ' -f1)
[ "$got" = "$UPSTREAM_SHA256" ] || { echo "SHA-256 mismatch for $UPSTREAM_APK: got $got" >&2; rm -f "$apk"; exit 1; }
echo "$apk"
