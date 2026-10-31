#!/bin/bash
# Builds dist/cabinwright.smarttube-v<version>.zip, an `app`-tier package: NEMESIS.data and one
# APK. Based on gen5-SmartTube's build.sh.
#
# usage: ./build.sh <revision 1-99>
#
# Needs: python3, Java, apktool 2.12.0 (APKTOOL), and Android build-tools (aapt, zipalign,
# apksigner) under $ANDROID_HOME (default ~/Library/Android/sdk).
# Signing: $SMARTTUBE_KEYSTORE, alias $SMARTTUBE_KEY_ALIAS (default smarttube), password in
# $SMARTTUBE_KEY_PASS. Every release must use the same key, or the store's update reinstalls
# SmartTube and wipes its settings and sign-in. The signer must match SIGNING_CERT_SHA256 in
# smarttube.conf, unless SMARTTUBE_TEST_BUILD=1 (a throwaway key, never to be released).
set -euo pipefail

REV=${1:?usage: build.sh <revision 1-99>}

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/smarttube.conf"
ANDROID_HOME=${ANDROID_HOME:-$HOME/Library/Android/sdk}
BT=$(ls -d "$ANDROID_HOME"/build-tools/* 2>/dev/null | sort -V | tail -1)
APKTOOL=${APKTOOL:-$(command -v apktool || true)}
KEYSTORE=${SMARTTUBE_KEYSTORE:-}
KEY_ALIAS=${SMARTTUBE_KEY_ALIAS:-smarttube}
DIST=$HERE/dist

die() { echo "build: $*" >&2; exit 1; }
[[ $REV =~ ^[0-9]+$ ]] && [ "$REV" -ge 1 ] && [ "$REV" -le 99 ] || die "revision must be 1-99"
[ -x "$BT/aapt" ] && [ -x "$BT/zipalign" ] && [ -x "$BT/apksigner" ] || die "Android build-tools not found under $ANDROID_HOME"
[ -n "$APKTOOL" ] && [ -x "$APKTOOL" ] || die "apktool not found (set APKTOOL)"
[ -f "$KEYSTORE" ] || die "keystore not found (set SMARTTUBE_KEYSTORE)"
[ -n "${SMARTTUBE_KEY_PASS:-}" ] || die "set SMARTTUBE_KEY_PASS"
if [ -z "${SMARTTUBE_TEST_BUILD:-}" ]; then
    [ -n "$SIGNING_CERT_SHA256" ] || die "SIGNING_CERT_SHA256 is empty in smarttube.conf"
fi

SRC_APK=$("$HERE/tools/fetch-upstream.sh")

# Upstream identity
"$BT/apksigner" verify --print-certs "$SRC_APK" 2>/dev/null \
    | grep -qi "certificate SHA-256 digest: $UPSTREAM_CERT_SHA256\$" || die "upstream APK isn't signed by upstream's key"
badging=$("$BT/aapt" dump badging "$SRC_APK")
pkg=$(sed -n "s/^package: name='\([^']*\)'.*/\1/p" <<< "$badging")
up_code=$(sed -n "s/^package: .*versionCode='\([0-9]*\)'.*/\1/p" <<< "$badging")
up_name=$(sed -n "s/^package: .*versionName='\([^']*\)'.*/\1/p" <<< "$badging")
[ "$pkg" = org.smarttube.stable ] || die "not SmartTube stable: $pkg"
grep -q "^native-code: .*'armeabi-v7a'" <<< "$badging" || die "not an armeabi-v7a build"
code=$((up_code * 100 + REV))
version=$up_name.$REV
echo "SmartTube $up_name ($up_code) -> $version, versionCode $code"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Patch. The notices go inside the APK: an `app`-tier zip holds nothing else.
"$APKTOOL" d -f -o "$work/src" "$SRC_APK" >/dev/null
python3 -I "$HERE/tools/patch.py" "$work/src" "$code"
mkdir -p "$work/src/assets/cabinwright-notices"
cp "$HERE/LICENSE" "$HERE/NOTICE.md" "$HERE"/notices/* "$work/src/assets/cabinwright-notices/"
"$APKTOOL" b -o "$work/unsigned.apk" "$work/src" >/dev/null
"$BT/zipalign" -f -p 4 "$work/unsigned.apk" "$work/aligned.apk"
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" --ks-pass env:SMARTTUBE_KEY_PASS \
    --min-sdk-version 19 --out "$work/smarttube.apk" "$work/aligned.apk" 2>/dev/null
rm -f "$work/smarttube.apk.idsig"

# Check the result, not just that the patch script ran
certs=$("$BT/apksigner" verify --min-sdk-version 19 --print-certs "$work/smarttube.apk" 2>/dev/null) \
    || die "signature doesn't verify for API 19"
if [ -n "$SIGNING_CERT_SHA256" ]; then
    grep -qi "certificate SHA-256 digest: $SIGNING_CERT_SHA256\$" <<< "$certs" \
        || die "signed with the wrong key (expected certificate SHA-256 $SIGNING_CERT_SHA256)"
fi
out=$("$BT/aapt" dump badging "$work/smarttube.apk")
grep -q "versionCode='$code'" <<< "$out" || die "versionCode not $code"
grep -q "uses-permission: name='android.permission.GET_TASKS'" <<< "$out" || die "GET_TASKS missing"
grep -q "uses-permission: name='com.hkmc.permission.AUTOMOTIVE_REGULATION'" <<< "$out" || die "AUTOMOTIVE_REGULATION missing"
urls=$("$BT/aapt" dump --values resources "$work/smarttube.apk" | python3 -I "$HERE/tools/resource_array.py" update_urls) \
    || die "update_urls missing from the built APK"
[ -z "$urls" ] || die "update_urls is '$urls', expected nothing"
manifest=$("$BT/aapt" dump xmltree "$work/smarttube.apk" AndroidManifest.xml)
grep -qF 'app.cabinwright.category.ALL_MENUS' <<< "$manifest" || die "the All Menus category is missing"
ime=$("$BT/aapt" dump xmltree "$work/smarttube.apk" res/layout/lb_search_bar.xml | grep -F 'android:imeOptions')
grep -q '=(type 0x11)0x3$' <<< "$ime" || die "search box imeOptions aren't plain actionSearch: $ime"

# Package
python3 -I - "$HERE/package/NEMESIS.data" "$work/smarttube.apk" "$version" "$DIST/cabinwright.smarttube-v$version.zip" <<'PY'
import sys, zipfile
from pathlib import Path
data, apk, version, out = sys.argv[1:5]
s = Path(data).read_text()
assert "@VERSION@" in s
Path(out).parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("NEMESIS.data", s.replace("@VERSION@", version))
    z.write(apk, "smarttube.apk")
PY
shasum -a 256 "$DIST/cabinwright.smarttube-v$version.zip"
