# howdy-moto

System-specific source, configuration snapshots, tests, and recovery notes for
Howdy IR face authentication on this Intel Core Ultra laptop, plus automatic
GNOME login-keyring unlocking after GDM login.

**Working project:** `~/Projects/howdy-moto`.
**Runtime code:** root-owned copies under `/usr/local/`; edits here do not change
login behavior until explicitly installed. Do not execute privileged code from
this user-writable project automatically at login.

## Current status

- Intel NPU backend enabled for existing GDM/swaylock Howdy integration; user
  confirmed face unlock works.
- 10 personal enrollment profiles, 120 embeddings; separate root-controlled
  runtime storage, not included here.
- Dedicated random GNOME login-keyring password configured and verified; root-only
  plaintext secret at `/etc/howdy-keyring/1000.secret`.
- Optional GDM **session** helper enabled. Manual invocation succeeds and login
  keyring is unlocked. Full next-login startup timing has not yet been tested.
- PAM authentication/account rules and Linux account password are unchanged.
- No account passwords, keyring passwords, personal face templates, or encrypted
  personal keyring backups are stored in this project.

## Quick commands

```sh
# No camera use, no password disclosure:
howdy-npu check --user <user>
sudo howdy-keyring unlock --user <user>

# Tests (disposable keyring on a separate bus; no camera):
cd ~/Projects/howdy-moto
python -m unittest discover -s tests -p 'test_*.py'
dbus-run-session -- python tests/integration_keyring.py
sh scripts/check-installation.sh
```

At your next normal GDM login, the browser should no longer ask for the login
keyring password. Lock-screen unlock is not equivalent to a new GDM session.
No reboot is required to activate the hook; a real logout/login is needed to test
its full startup path. Save work first and keep recovery commands available.

## Layout

| Path | Contents |
|---|---|
| `src/npu/backend.py` | Local explicit-NPU detection/alignment/recognition and enrollment |
| `src/keyring/` | Root admin/session helper and user-side Secret Service worker |
| `scripts/` | Install/configuration commands, wrappers, benchmarks and camera test |
| `tests/` | Matching/dispatch/security/PAM tests and isolated keyring integration test |
| `config/` | Current Howdy/PAM/udev snapshots; no personal enrollment data |
| `config/baseline/` | Original Howdy code/config for patch review, not blind restoration |
| `patches/` | Minimal local Howdy dispatch/config diffs |
| `models/` | Generic Open Model Zoo FP16 networks, not your face embeddings |
| `docs/` | System inventory, NPU/keyring details, security and maintenance notes |

## Read these before changing anything

- [System and benchmark inventory](docs/SYSTEM.md)
- [NPU backend/enrollment](docs/NPU.md)
- [Keyring design, setup, and recovery](docs/KEYRING.md)
- [Maintenance/install notes](docs/MAINTENANCE.md)

## Recovery

To undo the stored-keyring-password approach without losing saved items:

```sh
sudo howdy-keyring restore-password --user <user>
sudo howdy-keyring-pam disable
```

The first command prompts locally for a new manually known keyring password and
removes the stored random secret only after the keyring password change succeeds.
It does not change your Linux password. Use your Linux password there if you want
normal password-based login keyring unlocking again.

To restore original dlib Howdy separately:

```sh
sudo howdy-npu-rollback
```

**Restore the keyring password first if removing the helper.** NPU rollback
restores the original Howdy config/compare script but leaves the current keyring
session hook intact. Do not delete the keyring secret before restoring a known
keyring password; otherwise you may lose access to your stored secrets.

## Security limitations accepted for this setup

- Face backend is experimental: no calibrated false-accept guarantee or liveness.
  Requiring multiple matching frames is not a spoof-resistance check.
- A successful face impersonation also unlocks the keyring after GDM login.
- The dedicated keyring password is plaintext with root-only permissions.
- The root filesystem is not observed to be encrypted: offline SSD access can
  expose both the stored password and encrypted keyring. Root access can too.
- Secret handling avoids argv/environment/logs, but passwords necessarily exist
  briefly in process memory and on local IPC. Python memory is not guaranteed
  to be securely erased.

Do not publish personal runtime credentials, biometric enrollments, or private
backups. `.gitignore` is a safeguard, not a substitute for inspecting files.
