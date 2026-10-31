#!/bin/bash
# Checks tools/patch.py against the real upstream dex without apktool: disassembles it, applies
# the patches (with stand-ins for the manifest and resources, which only apktool can decode),
# reassembles it, and looks for the changes in the result. A patch that no longer fits upstream
# stops here rather than in a release.
#
# usage: tools/verify-smali.sh <upstream apk> <dir with baksmali-2.5.2.jar and smali-2.5.2.jar>
set -euo pipefail

APK=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
TOOLS=${2:?usage: verify-smali.sh <upstream apk> <smali tools dir>}
HERE=$(cd "$(dirname "$0")/.." && pwd)
ANDROID_HOME=${ANDROID_HOME:-$HOME/Library/Android/sdk}
BT=$(ls -d "$ANDROID_HOME"/build-tools/* 2>/dev/null | sort -V | tail -1)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

unzip -oq "$APK" 'classes*.dex' -d "$work/dex"
for d in "" 2 3; do
    out=smali${d:+_classes$d}
    java -jar "$TOOLS/baksmali-2.5.2.jar" d "$work/dex/classes$d.dex" -o "$work/src/$out"
done
mkdir -p "$work/src/res/values"
echo '<manifest package="org.smarttube.stable">' > "$work/src/AndroidManifest.xml"
echo '<resources><string-array name="update_urls"><item>x</item></string-array></resources>' > "$work/src/res/values/arrays.xml"
echo "versionCode: '1'" > "$work/src/apktool.yml"

python3 -I "$HERE/tools/patch.py" "$work/src" 245801

mkdir "$work/out"
for d in "" 2 3; do
    out=smali${d:+_classes$d}
    java -jar "$TOOLS/smali-2.5.2.jar" a --api 19 -j 1 "$work/src/$out" -o "$work/out/classes$d.dex"
    "$BT/dexdump" -d "$work/out/classes$d.dex" 2>/dev/null > "$work/out/classes$d.txt"
    methods=$("$BT/dexdump" -f "$work/out/classes$d.dex" 2>/dev/null | sed -n 's/^method_ids_size *: *//p')
    echo "classes$d.dex: $methods method ids"
    [ "$methods" -le 65536 ] || { echo "classes$d.dex has too many methods" >&2; exit 1; }
done

check() { grep -qF -- "$2" "$work"/out/*.txt && echo "ok: $1" || { echo "MISSING: $1" >&2; exit 1; }; }
check "guard is called from onCreate"       "org/gen5w/DrivingGuard;.onCreate:(Landroid/app/Activity;)V"
check "focus goes through CarSource"        "app/cabinwright/smarttube/CarSource;.requestFocus:"
check "CarSource uses the mode's focus"     "Landroid/media/AudioManager;.requestAudioFocus:(Landroid/media/AudioManager\$OnAudioFocusChangeListener;III)I"
check "unmute goes to MicomAudioManager"    "Lcom/hkmc/media/MicomAudioManager;.setMute:(I)Z"
check "focus gain is seen"                  "app/cabinwright/smarttube/CarSource;.onFocusChange:(I)V"

# The rethrow gate and the session, read from the assembled code
python3 -I - "$work/out" <<'PY'
import re, sys
from pathlib import Path
text = "".join(p.read_text(errors="replace") for p in sorted(Path(sys.argv[1]).glob("*.txt")))
m = re.search(r"MediaCodecUtil\.getDecoderInfosInternal:.*?catches", text, re.S)
body = m.group(0)
i = body.index("Skipping codec")
sys.exit("the isEmpty check is still there") if "isEmpty" in body[:i] else print("ok: dead codecs are skipped on an empty list")
PY
python3 -I - "$work/out" <<'PY'
import re, sys
from pathlib import Path
text = "".join(p.read_text(errors="replace") for p in sorted(Path(sys.argv[1]).glob("*.txt")))
m = re.search(r"DefaultAudioSink\.initialize:\(J\)V(.*?)buildAudioTrack", text, re.S)
sys.exit("session 29 is not set") if "#int 29" not in m.group(1) else print("ok: tracks are built on session 29")
PY
echo verified
