# Local experimental Howdy NPU backend

This documents the face backend. A separate optional GDM keyring session hook
was added later; see [KEYRING.md](KEYRING.md). Face authentication/account rules
remain unchanged. NPU rollback restores only Howdy config/compare code and does
not remove the later keyring session hook.

## Status and limitations

Explicit Intel NPU inference for face detection, five-point landmarks, and
aligned 256-dimensional face embeddings. No automatic CPU/dlib fallback while
NPU dispatch is enabled. Recognition/driver/model failures return nonzero so
the existing PAM password path remains available.

Not a calibrated authentication product: no liveness, false-accept guarantee,
or spoof-resistance claim. More profiles can increase false-accept exposure.
Three matching frames are a stability check, NOT a liveness check.

10 enrollment profiles / 120 embeddings were collected for <user>:
straight-normal, turn-left, turn-right, tilt-left, tilt-right, near, far,
dim-light, bright-light, gentle-motion. Fresh held-out tests matched 10/12
normal-use and 11/12 distance samples at cosine similarity >= 0.85. Separate
lighting validation, other-person rejection, and spoof testing were not
completed; the user explicitly accepted enabling with these limitations.

No camera images are saved. Face embeddings are sensitive biometric data.
Staging data and backups are root-only. Active templates are root-owned and
readable only by root and the account's private primary group, because swaylock
runs unprivileged. They are never writable by the account.

## Integration

- `/usr/lib/howdy/compare.py`: small dispatch before dlib imports; execs isolated
  Python (`-I`) with `/usr/local/lib/howdy-npu/backend.py auth --user USER`.
- `/etc/howdy/config.ini`: `[npu] enabled = true` enables this dispatch.
- `/usr/local/share/howdy-npu/models/`: root-owned FP16 Open Model Zoo models.
- `/var/lib/howdy-npu/users/UID.json`: active NPU templates.
- `/var/lib/howdy-npu/enrollment/UID.json`: root-only enrollment/validation staging.
- `/var/lib/howdy-npu/backup/`: original config, compare script, PAM files, dlib data.
- `/etc/udev/rules.d/70-howdy-npu-uaccess.rules`: active-seat Intel NPU access.
- Existing `pam_howdy.so` PAM lines in GDM and swaylock are unchanged. Existing
  account restrictions, SSH/lid rules and password paths are retained.
- Original dlib models remain untouched. The native PAM module still checks for
  `/etc/howdy/models/USER.dat`; do not delete it while using this integration.

Matches require >=0.85 cosine similarity in at least 3 consecutive usable
frames spanning >=0.25s. Dark IR frames do not count toward that requirement;
nonmatching/no-face/multiple-face usable frames reset it. Minimum face size is
60 pixels. Authentication has a 15-second hard limit including initialization,
with the configured scan timeout (currently 8 seconds) after model startup.
The legacy `video.certainty` setting does not set the NPU threshold.

## Commands

Check installation/device access without opening the camera:

    howdy-npu check --user <user>

Inspect enrollment labels and held-out scores (no images):

    sudo howdy-npu report --user <user>

Collect an additional labeled profile (camera opens immediately):

    sudo howdy-npu enroll --user <user> --label descriptive-new-condition

Collect held-out samples, without adding them to enrollment:

    sudo howdy-npu validate --user <user> --label fresh-condition

After changing enrollment, fresh validation is required before promotion:

    sudo howdy-npu promote --user <user>

`enroll` changes staging only. Active login templates do not change until
`promote` succeeds. Any enrollment change clears staged validation records.
The threshold is deliberately fixed in code; don't lower it to make tests pass.
The 80% held-out match rate requirement is an operational acceptance check,
not a false-accept/security assessment.

Run a standalone active-template recognition attempt (camera opens immediately):

    howdy-npu auth --user <user>

The normal `howdy add/list/remove/test` commands still manage/test the OLD dlib
backend, not the NPU templates. Use `howdy-npu` for the NPU backend.

## Disable / rollback

Return to the exact previous dlib configuration and compare script:

    sudo howdy-npu-rollback

This does not delete NPU templates, packages or the device-access rule. No reboot
or PAM edits are needed. Keep a working terminal open for the first real unlock.

To disable face authentication entirely, set `core.disabled = true` in
`/etc/howdy/config.ini`; password authentication remains unchanged.

## Maintenance

This is a LOCAL PATCH, not an upstream Howdy feature. Upgrading/reinstalling
Howdy may overwrite `compare.py` and remove dispatch. Inspect/reapply the dispatch
after Howdy upgrades; do not blindly restore an old full compare script over a
new version. After OpenVINO/driver/model upgrades, retest before relying on it.
System Python/OpenVINO packages are managed by pacman.

Models: Open Model Zoo 2023.0 FP16 face-detection-adas-0001,
landmarks-regression-retail-0009, face-reidentification-retail-0095.
Source: https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/
Model documentation: https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/intel
