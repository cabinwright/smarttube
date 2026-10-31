# Notices

This package is a modified build of SmartTube. The tooling in this repository is licensed under
the MIT License (`LICENSE`).

## SmartTube

https://github.com/yuliskov/SmartTube, Copyright (c) 2020-present yuliskov, MIT License
(`notices/SmartTube-LICENSE.txt`).

Built from the official release `32.68s`, file `SmartTube_stable_32.68_armeabi-v7a.apk`,
SHA-256 `2130b23b17ed5cfd324baec81750a2be22059212b6ee17449f21cae2cb3a60d9`.

SmartTube was published under the GNU General Public License version 3 until February 2026, when
its repository was recreated under the MIT License. So that this build is proper under either
licence, the GPL's text is included (`notices/GPL-3.0.txt`) and its complete source is public, and
stays public for as long as the build is offered:

- SmartTube's source at tag `32.68s`, with its submodules at the commits that tag records:
  https://github.com/yuliskov/SmartTube/tree/32.68s
- every change made to it: `tools/patch.py` in this repository, which is applied to the release
  above by `build.sh`.

## gen5-SmartTube

https://github.com/KramerTech/gen5-SmartTube, Copyright (c) 2026 Sean Kramer, MIT License
(`notices/gen5-SmartTube-LICENSE.txt`).

This port stands on Sean Kramer's work: working out why SmartTube fails on these head units, and
the patches for starting, TLS, the back swipe and the driving guard. `tools/patch.py`,
`tools/resource_array.py` and `build.sh` come from that project. The README says what was changed.

gen5-codec-patch (https://github.com/KramerTech/gen5-codec-patch, MIT) is where the cause of the
playback failure was found. None of its code or binaries are used here.

## What was changed from SmartTube

- `AndroidManifest.xml`: adds the permissions `android.permission.GET_TASKS` and
  `com.hkmc.permission.AUTOMOTIVE_REGULATION`
- `NetworkData.isConscryptEnabled()` always returns true
- `update_urls` is empty, so the in-app update check is off
- versionCode is upstream's versionCode * 100 + this package's revision
- `MotherActivity.initEdgeSlide()` enables the left-edge swipe on Android 4.4
- Slidr's `SliderPanel` gets an `onLayout` that keeps the swipe offset during a swipe
- `MotherActivity.onCreate()` calls a new class, `org.gen5w.DrivingGuard`
- ExoPlayer's `MediaCodecUtil` skips codecs it can't query even when no other codec was found
- ExoPlayer's `AudioFocusManager` and `DefaultAudioSink` use a new class,
  `app.cabinwright.smarttube.CarSource`, and the head unit's Music Streaming audio session
- `PlayerTweaksData.isAudioFocusEnabled()` always returns true
- the themes no longer set `android:windowFullscreen`, and `Helpers.makeActivityFullscreen2()`
  does nothing, so the system status bar stays
- `ExoPlayerInitializer.createLoadControl()` uses shorter buffer durations
- `SearchData` opens the keyboard on focus by default
- re-signed with this project's key

Third-party libraries inside the APK are distributed by upstream under their own licenses,
unchanged, except for the changes to ExoPlayer (Apache License 2.0) listed above.

SmartTube and this package are unofficial. They are not made by, or endorsed by, YouTube, Google,
Hyundai or Kia.
