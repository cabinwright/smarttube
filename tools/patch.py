"""Apply the head unit patches to an apktool-decoded SmartTube tree.

Patches 1 and 2 and 4 to 7 are from Sean Kramer's gen5-SmartTube (MIT); 3 and 7 are changed
here, and 8 and 9 are new. See NOTICE.md.

usage: patch.py <decoded dir> <version code>

Patches (each fails loudly if SmartTube changed underneath it):
  1. GET_TASKS permission: Hyundai's ActivityManager checks it in
     Activity.finish(), so without it the app dies on its splash screen.
  2. NetworkData.isConscryptEnabled() returns true: KitKat's system libssl
     crashes (SIGSEGV in ssl_parse_serverhello_tlsext) and there are no Play
     Services to provide a newer TLS stack; this routes HTTPS through the
     Conscrypt SmartTube already bundles.
  3. update_urls is emptied, which turns the in-app update check off: the
     store owns updates, and upstream's APK isn't patched or signed with our key.
  4. versionCode: upstream code * 100 + revision, so each of our revisions is
     an update over the last and over the upstream build of the same version.
  5. Swipe-from-left-edge = Back on Android 4.4: SmartTube already has it
     (MotherActivity.initEdgeSlide, the Slidr library; a finished slide calls
     onBackPressed) but only enables it on API 21+. Its API-21-only call in
     Slidr is version-guarded, so the gate is lowered to API 19.
  6. Edge swipe survives relayouts: Slidr's SliderPanel drags the content with
     offsetLeftAndRight, and any layout pass puts it back at 0. In the player
     the position text relayouts the window every second, so a swipe ends
     with the content at 0 and Slidr treats it as cancelled. SliderPanel gets
     an onLayout that restores the offset while a drag or settle is running.
  7. Driving regulation: Gen5W's com.hkmc.regulation service says when the car
     is out of park, but leaves it to each app to obey (its client-side
     register() is an empty stub). A new class, org.gen5w.DrivingGuard, is
     called from MotherActivity.onCreate (every SmartTube screen): if the car
     is regulated it shows Hyundai's "not available while driving" popup,
     finishes every screen's task (else ActivityManager relaunches them; the
     player has its own task) and kills the process. Otherwise it registers
     for ACTION_ENTER_REGULATION and does the same when the car leaves park
     (popup only if SmartTube was in use). Adds the normal-level
     AUTOMOTIVE_REGULATION permission. If the guard can't work (no service, or
     any error setting it up) it closes SmartTube: this package only runs on
     firmware where the service exists, so that means something is wrong.
  8. Dead codecs: this firmware's media_codecs.xml lists decoders that can't be
     instantiated, and getCapabilitiesForType() throws for them. ExoPlayer
     skips such a codec only if the list so far isn't empty, so a dead first
     entry (or the tunneled-playback query, where the working H.264 decoder
     is filtered out first) fails playback with DecoderQueryException.
     Skipping them always, on API 23 and below, leaves those formats reported
     as unsupported, and needs no change to the system. The one other caller,
     DeviceHelpers.getCodecMaxHeight, returns early below API 21.
  9. Car audio: the head unit's AudioFlinger mutes music tracks that aren't on
     the current source's session, and plain focus means "AV off". SmartTube
     becomes the Music Streaming source, as Cabinwright's CarAudio does: focus
     with mode 130, setMute(3) (also when focus comes back, since every mode
     change mutes), every track on session 29. The audio focus setting is
     forced on, since turning it off would leave SmartTube silent.
 10. Status bar on every screen but the player: the head unit's back and home
     live in its status bar, which SmartTube hides with android:windowFullscreen
     in its themes and with Helpers.makeActivityFullscreen2. Browse, search,
     sign-in and settings keep the bar. The player stays fullscreen, so patch 13
     gives it its own exit.
 11. Start sooner on a slow connection: playback starts with 1.5 s buffered
     instead of 2.5 s, 3 s instead of 5 s after a stall, and the Medium buffer,
     the default, is 15 s instead of 30 s. The buffer setting still offers
     High and Highest. The video default is left alone: on API 19 it is
     already 640x360 H.264.
 12. Search keyboard. The search box opens the keyboard when it gets focus, by
     default (still a setting). Sign-in needs no keyboard: it shows a code to
     enter on a phone. The stock keyboard crashes on leanback's privateImeOptions
     until the Cabinwright keyboard fix is installed.
 13. Close button: the first action in the player's controls leaves the video,
     the same way back does. Any touch brings the controls up
     (PlaybackActivity.dispatchTouchEvent), so it can't be stranded. Its icon is
     ic_close; the day variant is black, so the night variant's white PNGs
     replace it. Nothing else in SmartTube uses that drawable.
 14. Unmute after the mode change, not only before it. The focus grant returns
     before ModeManager changes mode, and that change mutes AV. An unmute that
     arrives during the change is held and sent when it ends, but one that
     arrives first is lost, and the source stays silent. CarSource unmutes again
     at 0.3, 0.8 and 1.8 s, and stops on a loss of focus or an abandon.
 15. All Menus: the activity the package opens (SplashActivity) gets a MAIN +
     app.cabinwright.category.ALL_MENUS filter, beside its launcher one, and the
     menu's meta-data. The icons are package/menu-res, made from
     package/glyph.svgpath with the SDK's menu_icon.py, in the stock 99x99 style;
     without them the menu would fall back to the 320x320 app icon.
"""
import re
import sys
from pathlib import Path



def add_permission(root: Path, name: str) -> None:
    p = root / "AndroidManifest.xml"
    s = p.read_text(encoding="utf-8")
    if f'android:name="{name}"' in s:
        return
    m = re.search(r"<manifest\b[^>]*>", s)
    if not m:
        raise SystemExit("AndroidManifest.xml: no <manifest> element")
    s = s[: m.end()] + f'\n    <uses-permission android:name="{name}"/>' + s[m.end():]
    p.write_text(s, encoding="utf-8")


def patch_get_tasks(root: Path) -> None:
    add_permission(root, "android.permission.GET_TASKS")


def patch_conscrypt(root: Path) -> None:
    hits = [
        f for d in sorted(root.glob("smali*"))
        for f in d.rglob("NetworkData.smali")
        if f.read_text(encoding="utf-8").startswith(".class public Lcom/liskovsoft/smartyoutubetv2/common/prefs/NetworkData;")
    ]
    if len(hits) != 1:
        raise SystemExit(f"NetworkData.smali: expected 1, found {len(hits)} - SmartTube changed, re-check the Conscrypt patch")
    p = hits[0]
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r"(\.method public isConscryptEnabled\(\)Z\n).*?(\.end method)", re.S)
    if not pat.search(s):
        raise SystemExit("isConscryptEnabled() not found - SmartTube changed, re-check the Conscrypt patch")
    s = pat.sub(r"\1    .locals 1\n\n    const/4 v0, 0x1\n\n    return v0\n\2", s, count=1)
    p.write_text(s, encoding="utf-8")


def patch_update_urls(root: Path) -> None:
    p = root / "res" / "values" / "arrays.xml"
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r'<string-array name="update_urls">.*?</string-array>|<string-array name="update_urls"\s*/>', re.S)
    if len(pat.findall(s)) != 1:
        raise SystemExit("arrays.xml: update_urls not found exactly once - SmartTube changed, re-check the updater patch")
    s = pat.sub('<string-array name="update_urls"></string-array>', s, count=1)
    p.write_text(s, encoding="utf-8")


def patch_version_code(root: Path, code: int) -> None:
    p = root / "apktool.yml"
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r"(versionCode:\s*)'?\d+'?")
    if len(pat.findall(s)) != 1:
        raise SystemExit("apktool.yml: versionCode not found exactly once")
    s = pat.sub(rf"\g<1>{code}", s, count=1)
    p.write_text(s, encoding="utf-8")


def patch_edge_slide(root: Path) -> None:
    hits = [
        f for d in sorted(root.glob("smali*"))
        for f in d.rglob("MotherActivity.smali")
        if f.read_text(encoding="utf-8").startswith(".class public Lcom/liskovsoft/smartyoutubetv2/common/misc/MotherActivity;")
    ]
    if len(hits) != 1:
        raise SystemExit(f"MotherActivity.smali: expected 1, found {len(hits)} - SmartTube changed, re-check the edge-slide patch")
    p = hits[0]
    s = p.read_text(encoding="utf-8")
    m = re.search(r"\.method private initEdgeSlide\(\)V\n.*?\.end method", s, re.S)
    if not m:
        raise SystemExit("initEdgeSlide() not found - SmartTube changed, re-check the edge-slide patch")
    body = m.group(0)
    gate = "    const/16 v1, 0x15\n"
    if body.count(gate) != 1 or "Lcom/r0adkll/slidr/Slidr;->attach" not in body:
        raise SystemExit("initEdgeSlide() no longer looks like an API 21 gate around Slidr.attach - re-check the edge-slide patch")
    s = s.replace(body, body.replace(gate, "    const/16 v1, 0x13\n"), 1)
    p.write_text(s, encoding="utf-8")


SLIDER_ON_LAYOUT = """
.method protected onLayout(ZIIII)V
    .locals 2

    iget-object v0, p0, Lcom/r0adkll/slidr/widget/SliderPanel;->decorView:Landroid/view/View;

    invoke-virtual {v0}, Landroid/view/View;->getLeft()I

    move-result v0

    invoke-super/range {p0 .. p5}, Landroid/widget/FrameLayout;->onLayout(ZIIII)V

    iget-object v1, p0, Lcom/r0adkll/slidr/widget/SliderPanel;->dragHelper:Lcom/r0adkll/slidr/util/ViewDragHelper;

    if-eqz v1, :done

    invoke-virtual {v1}, Lcom/r0adkll/slidr/util/ViewDragHelper;->getViewDragState()I

    move-result v1

    if-eqz v1, :done

    iget-object v1, p0, Lcom/r0adkll/slidr/widget/SliderPanel;->decorView:Landroid/view/View;

    invoke-virtual {v1}, Landroid/view/View;->getLeft()I

    move-result p1

    sub-int/2addr v0, p1

    invoke-virtual {v1, v0}, Landroid/view/View;->offsetLeftAndRight(I)V

    :done
    return-void
.end method
"""


def patch_slider_layout(root: Path) -> None:
    hits = [
        f for d in sorted(root.glob("smali*"))
        for f in d.rglob("SliderPanel.smali")
        if f.read_text(encoding="utf-8").startswith(".class public Lcom/r0adkll/slidr/widget/SliderPanel;")
    ]
    if len(hits) != 1:
        raise SystemExit(f"SliderPanel.smali: expected 1, found {len(hits)} - SmartTube changed, re-check the slider layout patch")
    p = hits[0]
    s = p.read_text(encoding="utf-8")
    needed = (
        ".super Landroid/widget/FrameLayout;",
        ".field private decorView:Landroid/view/View;",
        ".field private dragHelper:Lcom/r0adkll/slidr/util/ViewDragHelper;",
    )
    if not all(n in s for n in needed) or " onLayout(ZIIII)V" in s:
        raise SystemExit("SliderPanel no longer looks like Slidr's FrameLayout without an onLayout - re-check the slider layout patch")
    p.write_text(s.rstrip("\n") + "\n" + SLIDER_ON_LAYOUT, encoding="utf-8")


# In the main dex next to MotherActivity: on KitKat (legacy multidex) classes
# that run this early must be there. Keep it lean, the main dex is nearly full.
DRIVING_GUARD = """.class public Lorg/gen5w/DrivingGuard;
.super Landroid/content/BroadcastReceiver;
.source "DrivingGuard.java"


# WeakReferences to every screen created: the player runs in its own task,
# so finishing one task would leave another for ActivityManager to relaunch.
.field private static final sActivities:Ljava/util/ArrayList;

.field private static sReceiver:Lorg/gen5w/DrivingGuard;


.method static constructor <clinit>()V
    .locals 1

    new-instance v0, Ljava/util/ArrayList;

    invoke-direct {v0}, Ljava/util/ArrayList;-><init>()V

    sput-object v0, Lorg/gen5w/DrivingGuard;->sActivities:Ljava/util/ArrayList;

    return-void
.end method

.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V

    return-void
.end method

.method private static manager()Lcom/hkmc/regulation/IRegulationManager;
    .locals 1

    const-string v0, "com.hkmc.regulation"

    invoke-static {v0}, Landroid/os/ServiceManager;->getService(Ljava/lang/String;)Landroid/os/IBinder;

    move-result-object v0

    invoke-static {v0}, Lcom/hkmc/regulation/IRegulationManager$Stub;->asInterface(Landroid/os/IBinder;)Lcom/hkmc/regulation/IRegulationManager;

    move-result-object v0

    return-object v0
.end method

# Optionally show Hyundai's own regulation popup (drawn by the system, so it
# outlives us), finish every screen's task so ActivityManager has nothing to
# relaunch, then kill this process.
.method private static stop(Z)V
    .locals 4

    if-eqz p0, :finish

    :try_start_0
    invoke-static {}, Lorg/gen5w/DrivingGuard;->manager()Lcom/hkmc/regulation/IRegulationManager;

    move-result-object v0

    const-string v1, "SmartTube is not available while driving"

    const-string v2, "org.smarttube.stable"

    invoke-interface {v0, v1, v2}, Lcom/hkmc/regulation/IRegulationManager;->showRegulationPopup(Ljava/lang/String;Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :finish

    :finish
    sget-object v1, Lorg/gen5w/DrivingGuard;->sActivities:Ljava/util/ArrayList;

    invoke-virtual {v1}, Ljava/util/ArrayList;->size()I

    move-result v2

    :next
    if-eqz v2, :kill

    add-int/lit8 v2, v2, -0x1

    :try_start_1
    invoke-virtual {v1, v2}, Ljava/util/ArrayList;->get(I)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Ljava/lang/ref/WeakReference;

    invoke-virtual {v0}, Ljava/lang/ref/WeakReference;->get()Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Landroid/app/Activity;

    if-eqz v0, :next

    invoke-virtual {v0}, Landroid/app/Activity;->finishAffinity()V
    :try_end_1
    .catch Ljava/lang/Throwable; {:try_start_1 .. :try_end_1} :next

    goto :next

    :kill
    invoke-static {}, Landroid/os/Process;->myPid()I

    move-result v0

    invoke-static {v0}, Landroid/os/Process;->killProcess(I)V

    return-void
.end method

# From MotherActivity.onCreate. If the guard can't be set up, close: playing unguarded
# is the one thing that must not happen.
.method public static onCreate(Landroid/app/Activity;)V
    .locals 3

    sget-object v0, Lorg/gen5w/DrivingGuard;->sActivities:Ljava/util/ArrayList;

    new-instance v1, Ljava/lang/ref/WeakReference;

    invoke-direct {v1, p0}, Ljava/lang/ref/WeakReference;-><init>(Ljava/lang/Object;)V

    invoke-virtual {v0, v1}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z

    :try_start_0
    invoke-static {}, Lorg/gen5w/DrivingGuard;->manager()Lcom/hkmc/regulation/IRegulationManager;

    move-result-object v0

    if-eqz v0, :refuse

    invoke-interface {v0}, Lcom/hkmc/regulation/IRegulationManager;->getStatus()I

    move-result v0

    if-eqz v0, :parked

    const/4 v0, 0x1

    invoke-static {v0}, Lorg/gen5w/DrivingGuard;->stop(Z)V

    :parked
    sget-object v0, Lorg/gen5w/DrivingGuard;->sReceiver:Lorg/gen5w/DrivingGuard;

    if-nez v0, :done

    new-instance v0, Lorg/gen5w/DrivingGuard;

    invoke-direct {v0}, Lorg/gen5w/DrivingGuard;-><init>()V

    sput-object v0, Lorg/gen5w/DrivingGuard;->sReceiver:Lorg/gen5w/DrivingGuard;

    new-instance v1, Landroid/content/IntentFilter;

    const-string v2, "android.mobis.regulation.ACTION_ENTER_REGULATION"

    invoke-direct {v1, v2}, Landroid/content/IntentFilter;-><init>(Ljava/lang/String;)V

    invoke-virtual {p0}, Landroid/app/Activity;->getApplicationContext()Landroid/content/Context;

    move-result-object v2

    invoke-virtual {v2, v0, v1}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;)Landroid/content/Intent;
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :refuse

    :done
    return-void

    :refuse
    const/4 v0, 0x1

    invoke-static {v0}, Lorg/gen5w/DrivingGuard;->stop(Z)V

    return-void
.end method

# The car left park. Explain with the popup only if SmartTube was in use
# (foreground, visible or playing), not when it was just cached.
.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 2

    new-instance v0, Landroid/app/ActivityManager$RunningAppProcessInfo;

    invoke-direct {v0}, Landroid/app/ActivityManager$RunningAppProcessInfo;-><init>()V

    invoke-static {v0}, Landroid/app/ActivityManager;->getMyMemoryState(Landroid/app/ActivityManager$RunningAppProcessInfo;)V

    iget v0, v0, Landroid/app/ActivityManager$RunningAppProcessInfo;->importance:I

    const/16 v1, 0x12c

    if-ge v0, v1, :quiet

    const/4 v1, 0x1

    goto :stop

    :quiet
    const/4 v1, 0x0

    :stop
    invoke-static {v1}, Lorg/gen5w/DrivingGuard;->stop(Z)V

    return-void
.end method
"""


def patch_driving_guard(root: Path) -> None:
    hits = [
        f for d in sorted(root.glob("smali*"))
        for f in d.rglob("MotherActivity.smali")
        if f.read_text(encoding="utf-8").startswith(".class public Lcom/liskovsoft/smartyoutubetv2/common/misc/MotherActivity;")
    ]
    if len(hits) != 1:
        raise SystemExit(f"MotherActivity.smali: expected 1, found {len(hits)} - SmartTube changed, re-check the driving guard patch")
    p = hits[0]
    s = p.read_text(encoding="utf-8")
    m = re.search(r"\.method protected onCreate\(Landroid/os/Bundle;\)V\n.*?\.end method", s, re.S)
    sup = "    invoke-super {p0, p1}, Landroidx/fragment/app/FragmentActivity;->onCreate(Landroid/os/Bundle;)V\n"
    if not m or m.group(0).count(sup) != 1:
        raise SystemExit("MotherActivity.onCreate() no longer calls FragmentActivity.onCreate once - re-check the driving guard patch")
    body = m.group(0)
    hook = sup + "\n    invoke-static {p0}, Lorg/gen5w/DrivingGuard;->onCreate(Landroid/app/Activity;)V\n"
    s = s.replace(body, body.replace(sup, hook), 1)
    p.write_text(s, encoding="utf-8")

    dex_dir = next(d for d in root.glob("smali*") if d in p.parents)
    guard = dex_dir / "org" / "gen5w" / "DrivingGuard.smali"
    guard.parent.mkdir(parents=True)
    guard.write_text(DRIVING_GUARD, encoding="utf-8")
    add_permission(root, "com.hkmc.permission.AUTOMOTIVE_REGULATION")


def smali_file(root: Path, rel: str, what: str) -> Path:
    hits = [f for d in sorted(root.glob("smali*")) for f in [d / rel] if f.is_file()]
    if len(hits) != 1:
        raise SystemExit(f"{rel}: expected 1, found {len(hits)} - SmartTube changed, re-check the {what} patch")
    return hits[0]


def replace_once(s: str, old: str, new: str, what: str) -> str:
    if s.count(old) != 1:
        raise SystemExit(f"{what}: expected one match, found {s.count(old)} - SmartTube changed, re-check it")
    return s.replace(old, new)


def method(s: str, signature: str, what: str) -> str:
    m = re.search(re.escape(signature) + r"\n.*?\.end method", s, re.S)
    if not m:
        raise SystemExit(f"{what}: {signature} not found - SmartTube changed, re-check it")
    return m.group(0)


def patch_dead_codecs(root: Path) -> None:
    what = "dead codec patch"
    p = smali_file(root, "com/google/android/exoplayer2/mediacodec/MediaCodecUtil.smali", what)
    s = p.read_text(encoding="utf-8")
    m = re.search(r"\.method private static getDecoderInfosInternal\(.*?\.end method", s, re.S)
    if not m:
        raise SystemExit(f"{what}: getDecoderInfosInternal not found - SmartTube changed, re-check it")
    body = m.group(0)
    # Only the isEmpty() test goes: the label in front of it opens a try block.
    pat = re.compile(
        r"(?P<gate>    if-gt v\d+, v\d+, (?P<rethrow>:cond_[0-9a-f]+)\n\n(?:    :try_start_[0-9a-f]+\n)?)"
        r"    invoke-virtual \{v\d+\}, Ljava/util/ArrayList;->isEmpty\(\)Z\n\n"
        r"    move-result v\d+\n\n"
        r"    if-nez v\d+, (?P=rethrow)\n"
    )
    if len(pat.findall(body)) != 1:
        raise SystemExit(f"{what}: the SDK_INT <= 23 && !isEmpty() check isn't there - SmartTube changed, re-check it")
    p.write_text(s.replace(body, pat.sub(lambda g: g.group("gate"), body), 1), encoding="utf-8")


# Next to AudioFocusManager rather than in the main dex: it runs after multidex has loaded.
CAR_SOURCE = """.class public Lapp/cabinwright/smarttube/CarSource;
.super Ljava/lang/Object;
.source "CarSource.java"

.implements Ljava/lang/Runnable;


.field private static sContext:Landroid/content/Context;

.field private static sHandler:Landroid/os/Handler;


.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

# From AudioFocusManager's constructor: MicomAudioManager needs a Context.
.method public static init(Landroid/content/Context;)V
    .locals 2

    invoke-virtual {p0}, Landroid/content/Context;->getApplicationContext()Landroid/content/Context;

    move-result-object v0

    sput-object v0, Lapp/cabinwright/smarttube/CarSource;->sContext:Landroid/content/Context;

    new-instance v0, Landroid/os/Handler;

    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;

    move-result-object v1

    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V

    sput-object v0, Lapp/cabinwright/smarttube/CarSource;->sHandler:Landroid/os/Handler;

    return-void
.end method

.method public run()V
    .locals 0

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->unmute()V

    return-void
.end method

# A focus grant returns before ModeManager changes mode, and that change mutes AV
# (MicomAudioService.setAudioMode -> setMute(2)), so the unmute must also come after.
.method private static settle()V
    .locals 5

    sget-object v0, Lapp/cabinwright/smarttube/CarSource;->sHandler:Landroid/os/Handler;

    const/4 v1, 0x0

    invoke-virtual {v0, v1}, Landroid/os/Handler;->removeCallbacksAndMessages(Ljava/lang/Object;)V

    new-instance v1, Lapp/cabinwright/smarttube/CarSource;

    invoke-direct {v1}, Lapp/cabinwright/smarttube/CarSource;-><init>()V

    const-wide/16 v2, 0x12c

    invoke-virtual {v0, v1, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    const-wide/16 v2, 0x320

    invoke-virtual {v0, v1, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    const-wide/16 v2, 0x708

    invoke-virtual {v0, v1, v2, v3}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    return-void
.end method

# Every mode change mutes the AV channel, and the source's app unmutes it (3).
.method private static unmute()V
    .locals 3

    :try_start_0
    new-instance v0, Lcom/hkmc/media/MicomAudioManager;

    sget-object v1, Lapp/cabinwright/smarttube/CarSource;->sContext:Landroid/content/Context;

    invoke-direct {v0, v1}, Lcom/hkmc/media/MicomAudioManager;-><init>(Landroid/content/Context;)V

    const/4 v2, 0x3

    invoke-virtual {v0, v2}, Lcom/hkmc/media/MicomAudioManager;->setMute(I)Z
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :done

    :done
    return-void
.end method

# In place of AudioManager.requestAudioFocus(listener, stream, hint). 0x82 is
# ModeType.MUSICSTREAMING; DefaultAudioSink.initialize plays on its session, 29.
.method public static requestFocus(Landroid/media/AudioManager;Landroid/media/AudioManager$OnAudioFocusChangeListener;II)I
    .locals 2

    const/16 v0, 0x82

    invoke-virtual {p0, p1, p2, p3, v0}, Landroid/media/AudioManager;->requestAudioFocus(Landroid/media/AudioManager$OnAudioFocusChangeListener;III)I

    move-result v0

    const/4 v1, 0x1

    if-ne v0, v1, :done

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->unmute()V

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->settle()V

    :done
    return v0
.end method

# From AudioFocusManager.abandonAudioFocusDefault: the player stopped. The system gives focus and
# the mode to whoever held them before (Android Auto does its own unmute), so stop unmuting.
.method public static cancel()V
    .locals 2

    sget-object v0, Lapp/cabinwright/smarttube/CarSource;->sHandler:Landroid/os/Handler;

    const/4 v1, 0x0

    invoke-virtual {v0, v1}, Landroid/os/Handler;->removeCallbacksAndMessages(Ljava/lang/Object;)V

    return-void
.end method

# From AudioFocusListener.onAudioFocusChange: AUDIOFOCUS_GAIN after a call or a navigation prompt.
.method public static onFocusChange(I)V
    .locals 1

    if-gez p0, :regained

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->cancel()V

    return-void

    :regained
    const/4 v0, 0x1

    if-ne p0, v0, :done

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->unmute()V

    invoke-static {}, Lapp/cabinwright/smarttube/CarSource;->settle()V

    :done
    return-void
.end method
"""


def patch_car_audio(root: Path) -> None:
    what = "car audio patch"
    pkg = "com/google/android/exoplayer2/audio"
    cls = "Lapp/cabinwright/smarttube/CarSource;"

    p = smali_file(root, f"{pkg}/AudioFocusManager.smali", what)
    s = p.read_text(encoding="utf-8")
    plain = "invoke-virtual {v0, v1, v2, v3}, Landroid/media/AudioManager;->requestAudioFocus(Landroid/media/AudioManager$OnAudioFocusChangeListener;II)I"
    s = replace_once(s, plain, f"invoke-static {{v0, v1, v2, v3}}, {cls}->requestFocus(Landroid/media/AudioManager;Landroid/media/AudioManager$OnAudioFocusChangeListener;II)I", what)
    abandon = re.compile(r"(\.method private abandonAudioFocusDefault\(\)V\n    \.(?:locals|registers) \d+\n)")
    if len(abandon.findall(s)) != 1:
        raise SystemExit(f"{what}: abandonAudioFocusDefault changed - re-check it")
    s = abandon.sub(lambda g: g.group(1) + f"\n    invoke-static {{}}, {cls}->cancel()V\n", s)
    ctor = re.compile(r"(\.method public constructor <init>\(Landroid/content/Context;[^\n]*\n    \.(?:locals|registers) \d+\n)")
    if len(ctor.findall(s)) != 1:
        raise SystemExit(f"{what}: AudioFocusManager's constructor changed - re-check it")
    s = ctor.sub(lambda g: g.group(1) + f"\n    invoke-static {{p1}}, {cls}->init(Landroid/content/Context;)V\n", s)
    p.write_text(s, encoding="utf-8")
    dex_dir = next(d for d in root.glob("smali*") if d in p.parents)
    source = dex_dir / "app" / "cabinwright" / "smarttube" / "CarSource.smali"
    source.parent.mkdir(parents=True)
    source.write_text(CAR_SOURCE, encoding="utf-8")

    p = smali_file(root, f"{pkg}/AudioFocusManager$AudioFocusListener.smali", what)
    s = p.read_text(encoding="utf-8")
    entry = re.compile(r"(\.method public onAudioFocusChange\(I\)V\n    \.(?:locals|registers) \d+\n)")
    if len(entry.findall(s)) != 1:
        raise SystemExit(f"{what}: onAudioFocusChange changed - re-check it")
    s = entry.sub(lambda g: g.group(1) + f"\n    invoke-static {{p1}}, {cls}->onFocusChange(I)V\n", s)
    p.write_text(s, encoding="utf-8")

    p = smali_file(root, f"{pkg}/DefaultAudioSink.smali", what)
    s = p.read_text(encoding="utf-8")
    body = method(s, ".method private initialize(J)V", what)
    field = "    iget v3, p0, Lcom/google/android/exoplayer2/audio/DefaultAudioSink;->audioSessionId:I\n"
    build = "buildAudioTrack(ZLcom/google/android/exoplayer2/audio/AudioAttributes;I)Landroid/media/AudioTrack;"
    if body.count(field) != 1 or body.count(build) != 1 or body.index(field) > body.index(build):
        raise SystemExit(f"{what}: DefaultAudioSink.initialize changed - re-check it")
    s = s.replace(body, body.replace(field, "    const/16 v3, 0x1d\n"), 1)
    p.write_text(s, encoding="utf-8")

    p = smali_file(root, "com/liskovsoft/smartyoutubetv2/common/prefs/PlayerTweaksData.smali", what)
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r"(\.method public isAudioFocusEnabled\(\)Z\n).*?(\.end method)", re.S)
    if len(pat.findall(s)) != 1:
        raise SystemExit(f"{what}: isAudioFocusEnabled() not found - re-check it")
    s = pat.sub(r"\1    .locals 1\n\n    const/4 v0, 0x1\n\n    return v0\n\2", s, count=1)
    p.write_text(s, encoding="utf-8")


def patch_status_bar(root: Path) -> None:
    what = "status bar patch"
    # In every qualified values folder: API 19 reads values-v19 over values.
    style = re.compile(r'<style name="(?P<name>[^"]+)"[^>]*(?<!/)>.*?</style>', re.S)
    full = '<item name="android:windowFullscreen">true</item>'
    off = '<item name="android:windowFullscreen">false</item>'
    changed = set()

    def theme(g: "re.Match[str]") -> str:
        if not g.group("name").startswith("App.Theme.") or g.group("name").endswith(".Player") or full not in g.group(0):
            return g.group(0)
        changed.add(g.group("name"))
        return g.group(0).replace(full, off)

    for p in sorted(root.glob("res/values*/styles.xml")):
        s = p.read_text(encoding="utf-8")
        p.write_text(style.sub(theme, s), encoding="utf-8")
    if "App.Theme.Leanback.Browse" not in changed:
        raise SystemExit(f"{what}: the browse theme no longer sets windowFullscreen - SmartTube changed, re-check it")

    p = smali_file(root, "com/liskovsoft/sharedutils/helpers/Helpers.smali", what)
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r"(\.method public static makeActivityFullscreen2\(Landroid/app/Activity;\)V\n    \.(?:locals|registers) \d+\n)")
    if len(pat.findall(s)) != 1:
        raise SystemExit(f"{what}: makeActivityFullscreen2 not found - SmartTube changed, re-check it")
    only = (
        "\n    instance-of v0, p0, Lcom/liskovsoft/smartyoutubetv2/tv/ui/playback/PlaybackActivity;\n\n"
        "    if-nez v0, :cabinwright_player\n\n    return-void\n\n    :cabinwright_player\n"
    )
    p.write_text(pat.sub(lambda g: g.group(1) + only, s, count=1), encoding="utf-8")


CLOSE_ACTION = """.class public Lapp/cabinwright/smarttube/CloseAction;
.super Landroidx/leanback/widget/Action;
.source "CloseAction.java"


# Icon: ic_close, a white PNG on API 19 once patch_close_button has swapped it. That function
# takes the id from public.xml.
.method public constructor <init>(Landroid/content/Context;)V
    .locals 2

    const-wide/32 v0, 0x7f0a0fff

    invoke-direct {p0, v0, v1}, Landroidx/leanback/widget/Action;-><init>(J)V

    const v0, @ICON@

    invoke-static {p1, v0}, Landroidx/core/content/ContextCompat;->getDrawable(Landroid/content/Context;I)Landroid/graphics/drawable/Drawable;

    move-result-object v0

    invoke-virtual {p0, v0}, Landroidx/leanback/widget/Action;->setIcon(Landroid/graphics/drawable/Drawable;)V

    const-string v0, "Close"

    invoke-virtual {p0, v0}, Landroidx/leanback/widget/Action;->setLabel1(Ljava/lang/CharSequence;)V

    return-void
.end method

# PlaybackActivity.finish() is what back ends in, so the player closes the same way.
.method public static close(Landroid/content/Context;)V
    .locals 1

    instance-of v0, p0, Landroid/app/Activity;

    if-eqz v0, :done

    check-cast p0, Landroid/app/Activity;

    invoke-virtual {p0}, Landroid/app/Activity;->finish()V

    :done
    return-void
.end method
"""


def patch_close_button(root: Path) -> None:
    what = "close button patch"
    cls = "Lapp/cabinwright/smarttube/CloseAction;"
    glue = "com/liskovsoft/smartyoutubetv2/tv/ui/playback/other/VideoPlayerGlue.smali"
    public = (root / "res" / "values" / "public.xml").read_text(encoding="utf-8")
    m = re.search(r'<public type="drawable" name="ic_close" id="(0x7f[0-9a-f]{6})" />', public)
    if not m:
        raise SystemExit(f"{what}: ic_close isn't in public.xml - SmartTube changed, re-check it")
    icon = m.group(1)
    p = smali_file(root, glue, what)
    s = p.read_text(encoding="utf-8")
    context = "Landroidx/leanback/media/PlaybackGlue;->getContext()Landroid/content/Context;"
    # .locals from apktool, .registers from baksmali: two free registers in one, one in the other.
    first = re.compile(r"(\.method protected onCreatePrimaryActions\(Landroidx/leanback/widget/ArrayObjectAdapter;\)V\n    \.(?:locals 2|registers 4)\n)")
    click = re.compile(r"(\.method public onActionClicked\(Landroidx/leanback/widget/Action;\)V\n    \.(?:locals 1|registers 3)\n)")
    if len(first.findall(s)) != 1 or len(click.findall(s)) != 1:
        raise SystemExit(f"{what}: VideoPlayerGlue changed - re-check it")
    s = first.sub(lambda g: g.group(1) + (
        f"\n    new-instance v0, {cls}\n\n"
        f"    invoke-virtual {{p0}}, {context}\n\n    move-result-object v1\n\n"
        f"    invoke-direct {{v0, v1}}, {cls}-><init>(Landroid/content/Context;)V\n\n"
        "    invoke-virtual {p1, v0}, Landroidx/leanback/widget/ArrayObjectAdapter;->add(Ljava/lang/Object;)V\n"
    ), s)
    s = click.sub(lambda g: g.group(1) + (
        f"\n    instance-of v0, p1, {cls}\n\n    if-eqz v0, :cabinwright_not_close\n\n"
        f"    invoke-virtual {{p0}}, {context}\n\n    move-result-object v0\n\n"
        f"    invoke-static {{v0}}, {cls}->close(Landroid/content/Context;)V\n\n    return-void\n\n"
        "    :cabinwright_not_close\n"
    ), s)
    p.write_text(s, encoding="utf-8")
    dex_dir = next(d for d in root.glob("smali*") if d in p.parents)
    source = dex_dir / "app" / "cabinwright" / "smarttube" / "CloseAction.smali"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(CLOSE_ACTION.replace("@ICON@", icon), encoding="utf-8")

    pngs = sorted(root.glob("res/drawable-night-*dpi/ic_close.png"))
    if not pngs:
        raise SystemExit(f"{what}: no white ic_close PNGs - SmartTube changed, re-check it")
    for png in pngs:
        (root / "res" / png.parent.name.replace("-night", "") / png.name).write_bytes(png.read_bytes())


def patch_startup(root: Path) -> None:
    what = "startup patch"
    p = smali_file(root, "com/liskovsoft/smartyoutubetv2/common/exoplayer/other/ExoPlayerInitializer.smali", what)
    s = p.read_text(encoding="utf-8")
    body = method(s, ".method private createLoadControl()Lcom/google/android/exoplayer2/DefaultLoadControl;", what)
    new = body
    for old, repl in (
        ("    const/16 v2, 0x7530\n", "    const/16 v2, 0x3a98\n"),  # Medium: 15 s
        ("    const/16 v1, 0x7530\n", "    const/16 v1, 0x3a98\n"),
        ("    const/16 v3, 0x9c4\n", "    const/16 v3, 0x5dc\n"),  # to start: 1.5 s
        ("    const/16 v4, 0x1388\n", "    const/16 v4, 0xbb8\n"),  # after a stall: 3 s
    ):
        new = replace_once(new, old, repl, what)
    p.write_text(s.replace(body, new, 1), encoding="utf-8")


MENU_ENTRY = """
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="app.cabinwright.category.ALL_MENUS"/>
            </intent-filter>
            <meta-data android:name="app.cabinwright.icon" android:resource="@drawable/menu_icon"/>
            <meta-data android:name="app.cabinwright.icon_disabled" android:resource="@drawable/menu_icon_dis"/>
            <meta-data android:name="app.cabinwright.label" android:resource="@string/app_name"/>"""


def patch_menu_entry(root: Path) -> None:
    what = "menu entry patch"
    p = root / "AndroidManifest.xml"
    s = p.read_text(encoding="utf-8")
    pat = re.compile(r'<activity\b[^>]*android:name="com\.liskovsoft\.smartyoutubetv2\.tv\.ui\.main\.SplashActivity"[^>]*(?<!/)>')
    if len(pat.findall(s)) != 1:
        raise SystemExit(f"{what}: SplashActivity not found once - SmartTube changed, re-check it")
    p.write_text(pat.sub(lambda g: g.group(0) + MENU_ENTRY, s, count=1), encoding="utf-8")
    icons = Path(__file__).resolve().parent.parent / "package" / "menu-res"
    for icon in sorted(icons.glob("*/*.png")):
        out = root / "res" / icon.parent.name / icon.name
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(icon.read_bytes())


def patch_keyboard_default(root: Path) -> None:
    what = "keyboard default patch"
    p = smali_file(root, "com/liskovsoft/smartyoutubetv2/common/prefs/SearchData.smali", what)
    s = p.read_text(encoding="utf-8")
    pat = re.compile(
        r"(    const/4 v2, 0x1\n.*?const/4 v3, 0x3\n\n(?:    \.line \d+\n)?    invoke-static \{v0, v3, )v1(\}, Lcom/liskovsoft/sharedutils/helpers/Helpers;->parseBoolean\(\[Ljava/lang/String;IZ\)Z\n\n"
        r"    move-result v3\n\n(?:    \.line \d+\n)?    iput-boolean v3, p0, Lcom/liskovsoft/smartyoutubetv2/common/prefs/SearchData;->mIsKeyboardAutoShowEnabled:Z)",
        re.S,
    )
    if len(pat.findall(s)) != 1:
        raise SystemExit(f"{what}: SearchData's restore changed - re-check it")
    p.write_text(pat.sub(r"\1v2\2", s, count=1), encoding="utf-8")


def main() -> None:
    root, code = Path(sys.argv[1]), int(sys.argv[2])
    patch_get_tasks(root)
    patch_conscrypt(root)
    patch_update_urls(root)
    patch_version_code(root, code)
    patch_edge_slide(root)
    patch_slider_layout(root)
    patch_driving_guard(root)
    patch_dead_codecs(root)
    patch_car_audio(root)
    patch_status_bar(root)
    patch_startup(root)
    patch_keyboard_default(root)
    patch_close_button(root)
    patch_menu_entry(root)
    print(f"patched: GET_TASKS, Conscrypt, update check off, versionCode={code}, edge-swipe back (+ relayout fix), driving guard (fails closed), dead codecs, car audio, status bar outside the player, startup, search keyboard, close button, menu entry")


if __name__ == "__main__":
    main()
