# SmartTube for Cabinwright

[SmartTube](https://github.com/yuliskov/SmartTube) for the 2023 Kia EV6 head unit (Gen5W, Android
4.4), as an `app`-tier package for the [Cabinwright](https://github.com/cabinwright/store) store.
It is built on Sean Kramer's [gen5-SmartTube](https://github.com/KramerTech/gen5-SmartTube); see
[NOTICE.md](NOTICE.md).

The package is one APK. It changes nothing in `/system`, runs nothing as root and asks for no
capabilities. Everything is patched into the app (`tools/patch.py`).

## What differs from gen5-SmartTube

| | gen5-SmartTube | here |
|---|---|---|
| Video | needs gen5-codec-patch, which adds decoders to `/system` and edits `media_codecs.xml` | ExoPlayer skips the firmware's dead codecs (patch 8), so nothing outside the app changes |
| Sound | not handled | SmartTube becomes the Music Streaming source (patch 9); without it, the head unit mutes the app |
| Out of park | closes, but plays on if the regulation service can't be reached | closes in that case too |
| Updates | in-app check against its own releases | off; the store owns updates |
| Install hooks, `depwatch` service | yes, as root | none |

Formats: H.264 plays on the hardware decoder. VP9 and HEVC are reported as unsupported, because
this package adds no decoders, so SmartTube has to pick H.264.

## Build

```sh
tools/verify-smali.sh <upstream apk> <dir with baksmali/smali 2.5.2>   # patches against the real dex
SMARTTUBE_KEYSTORE=... SMARTTUBE_KEY_PASS=... APKTOOL=... ./build.sh 1  # dist/cabinwright.smarttube-v32.68.1.zip
```

`build.sh` downloads the pinned upstream APK and refuses it unless both its SHA-256 and its
signing certificate match `smarttube.conf`.

Use a key of its own for this package and put its certificate digest in `smarttube.conf`.
`SMARTTUBE_TEST_BUILD=1` allows a throwaway key while `SIGNING_CERT_SHA256` is empty.

## Before the first release

The patches are checked against the dex, but none of this has run on a car yet. On a parked car,
with a test build:

1. SmartTube opens and loads pages (patches 1, 2).
2. A video plays, picture first: look for `Skipping codec` in logcat (patch 8), and check that
   SmartTube finds H.264 for ordinary videos.
3. Sound comes out, the knob works, and the source comes back when SmartTube is closed (patch 9).
   Check again after a phone call, a navigation prompt, and with SmartTube killed mid-video. After
   a restart, check the car doesn't come up on a silent Music Streaming source.
4. With the foot on the brake: shift out of Park. SmartTube must close, whether it is playing,
   paused or in the background. Then try to open it in Drive. Do this first with the car held
   stationary; note whether the guard acts on the gear or only on moving.
