# Cloud emulator: AVD snapshot persistence across AMI bake

**Date:** 2026-05-10
**Surface:** `infra/mobile-ami/` (Packer + AMI bake)
**Audience:** anyone re-running `packer build` or debugging "snapshot loaded but app isn't installed"

## Symptom

After baking an AMI with the Packer pipeline:

1. The bake script's CommCare install + +7426 demo registration succeed.
2. `adb emu avd snapshot save cc-2.62.0-registered` returns `OK`.
3. `adb emu avd snapshot list` confirms the snapshot exists.
4. AMI is captured by Packer.
5. **At runtime**, the emulator boots from `-snapshot cc-2.62.0-registered`, but `pm list packages | grep commcare` returns nothing. CommCare is missing.

The self-heal in `ace-emulator-launch` papers over this by re-installing the APK from `/opt/ace/apks/<version>/` after boot, but that's a workaround.

## Root cause

The emulator's `-no-snapshot-save` flag interacts with named snapshots in a way that's not in the docs:

- **Without** `-no-snapshot-save`: on emulator exit, QEMU writes the userdata-qemu.img.qcow2 overlay's pending changes back to disk, and the named snapshot's referenced files (ram.bin, textures.bin, disk delta) are flushed.
- **With** `-no-snapshot-save`: on emulator exit, QEMU **discards** the qcow2 overlay. The named snapshot's `snapshot.pb` (metadata header) is written, but all the *referenced* data files are gone with the overlay. AMI capture preserves the 11-byte `snapshot.pb` and nothing else.

What we found, post-bake, on the live AMI:

```
$ ls -la /home/ubuntu/.android/avd/ACE_Pixel_API_34.avd/snapshots/cc-2.62.0-registered/
-rw-r--r-- 1 ubuntu ubuntu 11 ... snapshot.pb        # ← only metadata
```

A snapshot saved at runtime (with the runtime's flags) creates **3.4 GB** of files:

```
$ ls -la /home/ubuntu/.android/avd/ACE_Pixel_API_34.avd/snapshots/test-runtime-snap/
-rw-r--r-- 1 ubuntu ubuntu       4225 ... hardware.ini
-rw-r--r-- 1 ubuntu ubuntu 3594969412 ... ram.bin
-rw-r--r-- 1 ubuntu ubuntu    1844840 ... screenshot.png
-rw-r--r-- 1 ubuntu ubuntu       1070 ... snapshot.pb
-rw-r--r-- 1 ubuntu ubuntu   16027879 ... textures.bin
```

So `adb emu avd snapshot save` works fine. The bake just throws the data away on exit.

## Fix

**Drop `-no-snapshot-save` from the bake-time emulator launch.** Keep it at runtime — different concern.

`infra/mobile-ami/scripts/50-bake-snapshot.sh`:

```diff
 nohup emulator -avd $AVD_NAME \
   -no-window -no-audio -no-metrics \
   -gpu swiftshader_indirect \
-  -no-snapshot-save -no-snapshot-load \
+  -no-snapshot-load \
   -no-boot-anim \
   -wipe-data \
   > "$EMULATOR_LOG" 2>&1 &
```

`-no-snapshot-load` stays — we always cold-boot per version so prior versions don't bleed in. We just don't want to discard the new state on exit.

`infra/mobile-ami/files/ace-emulator-launch` keeps `-no-snapshot-save` in the runtime launch — read-only-snapshot semantics are correct for the runtime path (each session shouldn't accumulate state).

## How to verify after re-bake

After `packer build` produces a new AMI, before relying on it:

```bash
# On a runtime instance launched from the new AMI:
ssm-into-instance
ls -la /home/ubuntu/.android/avd/ACE_Pixel_API_34.avd/snapshots/cc-*/
# Expect: ram.bin (~3.4 GB), textures.bin, screenshot.png, snapshot.pb,
# hardware.ini — multiple files totaling >2 GB. Not just snapshot.pb.
```

If only `snapshot.pb` is present, the snapshot is empty and self-heal will trigger on every cold start.

## Related

- The runtime self-heal in `ace-emulator-launch` is independently valuable — it covers other failure modes (manual SSM `pm uninstall`, future filesystem corruption). Keep it even after this fix lands.
- The qcow2-overlay-on-exit semantics are documented inconsistently across Android emulator versions (verified misbehavior on 36.5.11). If a future emulator bump changes the behavior, re-test the bake before assuming the fix still holds.
