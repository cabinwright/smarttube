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
echo '<manifest package="org.smarttube.stable"><activity android:name="com.liskovsoft.smartyoutubetv2.tv.ui.main.SplashActivity"></activity>' > "$work/src/AndroidManifest.xml"
echo '<resources><string-array name="update_urls"><item>x</item></string-array></resources>' > "$work/src/res/values/arrays.xml"
echo "versionCode: '1'" > "$work/src/apktool.yml"
{
    echo '<resources>'
    for t in Browse GuidedStep Player Preferences.Base; do
        echo "<style name=\"App.Theme.Leanback.$t\"><item name=\"android:windowFullscreen\">true</item></style>"
    done
    echo '</resources>'
} > "$work/src/res/values/styles.xml"

mkdir -p "$work/src/res/drawable-night-xhdpi" "$work/src/res/drawable-xhdpi"
echo '<public type="drawable" name="ic_close" id="0x7f0800ca" />' > "$work/src/res/values/public.xml"
echo white > "$work/src/res/drawable-night-xhdpi/ic_close.png"
echo black > "$work/src/res/drawable-xhdpi/ic_close.png"

python3 -I "$HERE/tools/patch.py" "$work/src" 245801

# The themes, icon and menu entry, in the stand-ins
python3 -I - "$work/src/res" <<'PY'
import re, sys
from pathlib import Path
res = Path(sys.argv[1])
s = (res / "values/styles.xml").read_text()
full = lambda t: re.search(r'name="App\.Theme\.Leanback\.%s">.*?windowFullscreen">(\w+)' % re.escape(t), s).group(1)
if full("Player") != "true" or {full(t) for t in ("Browse", "GuidedStep", "Preferences.Base")} != {"false"}:
    sys.exit("only the player's theme should be fullscreen")
print("ok: only the player's theme is fullscreen")
if (res / "drawable-xhdpi/ic_close.png").read_text() != "white\n":
    sys.exit("the close icon is still the black one")
print("ok: the close icon is white")
s = (res.parent / "AndroidManifest.xml").read_text()
if "app.cabinwright.category.ALL_MENUS" not in s.split("</activity>")[0].split("SplashActivity")[1]:
    sys.exit("SplashActivity isn't in All Menus")
for name in ("drawable-hdpi/menu_icon.png", "drawable-hdpi/menu_icon_dis.png", "drawable-night-hdpi/menu_icon.png", "drawable-night-hdpi/menu_icon_dis.png"):
    if not (res / name).is_file():
        sys.exit("missing " + name)
print("ok: SplashActivity is in All Menus, with its icons")
PY

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
python3 -I - "$work/out" <<'PY'
import re, sys
from pathlib import Path
text = "".join(p.read_text(errors="replace") for p in sorted(Path(sys.argv[1]).glob("*.txt")))
m = re.search(r"ExoPlayerInitializer\.createLoadControl:.*?catches", text, re.S).group(0)
for v in ("#int 15000", "#int 1500", "#int 3000"):
    if v not in m:
        sys.exit("createLoadControl lacks " + v)
if "#int 30000" in m or "#int 2500" in m:
    sys.exit("createLoadControl still has the old values")
print("ok: startup thresholds")
m = re.search(r"Helpers\.makeActivityFullscreen2:.*?catches", text, re.S).group(0)
if "instance-of" not in m.split("return-void")[0] or "PlaybackActivity" not in m:
    sys.exit("makeActivityFullscreen2 isn't limited to the player")
print("ok: only the player hides the bar")
m = re.search(r"VideoPlayerGlue\.onCreatePrimaryActions:.*?catches", text, re.S).group(0)
if m.find("CloseAction") < 0 or m.find("CloseAction") > m.find("isPlayerButtonEnabled"):
    sys.exit("the close action isn't first")
m = re.search(r"VideoPlayerGlue\.onActionClicked:.*?catches", text, re.S).group(0)
if "CloseAction;.close:" not in m:
    sys.exit("the close action does nothing")
print("ok: close action is first and closes")
m = re.search(r"CarSource\.requestFocus:.*?catches", text, re.S).group(0)
if "CarSource;.settle:" not in m:
    sys.exit("no unmute after the mode change")
m = re.search(r"CarSource\.settle:.*?catches", text, re.S).group(0)
if m.count("postDelayed") != 3:
    sys.exit("settle doesn't retry")
m = re.search(r"AudioFocusManager\.abandonAudioFocusDefault:.*?catches", text, re.S).group(0)
if not 0 <= m.find("CarSource;.cancel:") < m.find("AudioManager;.abandonAudioFocus:"):
    sys.exit("abandoning focus doesn't cancel the unmutes")
print("ok: unmute follows the mode change and ends with the focus")
m = re.search(r"CloseAction\.<init>:.*?catches", text, re.S).group(0)
if "7f0800ca" not in m:
    sys.exit("the close action doesn't use ic_close")
print("ok: close action uses ic_close")
m = re.search(r"SearchBar\.onFinishInflate:.*?catches", text, re.S).group(0)
if "setOnEditorActionListener" not in m:
    sys.exit("the search box has lost its editor action listener")
print("ok: the search box keeps its editor action listener")
PY
echo verified
