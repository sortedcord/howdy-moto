# Installation and maintenance

## Root/user separation

This project is user-writable. Login uses installed **root-owned copies**, not
files from `~/Projects`. Review code and tests before explicitly installing edits.
Do not add sudoers exemptions, setuid bits, or writable privileged scripts.

Keyring helper installation (does NOT collect a password or enable PAM):

```sh
cd ~/Projects/howdy-moto
python -m unittest discover -s tests -p 'test_*.py'
dbus-run-session -- python tests/integration_keyring.py
sudo sh scripts/install-keyring.sh
```

For a first-time setup only, run the hidden local password prompt and enable hook:

```sh
sudo howdy-keyring setup --user <user>
sudo howdy-keyring-pam enable
```

Already configured on this laptop; do not rerun first-time setup unnecessarily.
The enable/disable tools edit only the exact optional hook, not authentication.

## NPU installation reconstruction

Dependencies on this Arch system:

```sh
sudo pacman -S --needed python-openvino openvino-intel-npu-plugin python-opencv
```

Initial dependency installation also installed Intel NPU driver/compiler and
Level Zero loader. The existing `intel_vpu` kernel driver was already loaded.
A reboot may be needed after driver/firmware upgrades.

The authoritative deployed source is copied in `src/npu/backend.py`. Runtime
layout:

- `/usr/local/lib/howdy-npu/backend.py`, root:root 644.
- `/usr/local/share/howdy-npu/models/`, root-owned generic models.
- `/usr/local/sbin/howdy-npu`, root:root 755.
- `/usr/local/sbin/howdy-npu-rollback`, root:root 755.
- `/var/lib/howdy-npu/`, root:root 711.
- `/var/lib/howdy-npu/enrollment/` and `backup/`, root-only 700.
- `/var/lib/howdy-npu/users/`, root:root 711; active UID-1000 template is
  root:<user> 640, allowing unprivileged swaylock to read but not modify it.
- `/etc/udev/rules.d/70-howdy-npu-uaccess.rules`: root:root 644, active-seat NPU access.
- `patches/howdy-npu-dispatch.patch`: minimal compare-script dispatch.
- `patches/howdy-npu-config.patch`: adds `[npu] enabled = true`.

Generic network files in `models/` are rediscoverable downloads. `SHA256SUMS`
records local downloaded-file checksums, not independent upstream signatures.
Benchmarks use the project's model directory; the deployed backend uses the fixed
root-owned model path.

Personal enrollments/backups are intentionally absent. Rebuilding the integration
from scratch requires enrolling again. Keep the original dlib enrollment file
for the native `pam_howdy.so` precheck. Do not copy a dummy enrollment into place
or bypass account restrictions.

For an existing installation, carefully reviewed backend edits can be deployed:

```sh
sudo install -o root -g root -m 644 src/npu/backend.py /usr/local/lib/howdy-npu/backend.py
```

No automatic face-login reinstall script is provided: blind overwriting of PAM,
compare code, or biometric state is unsafe. Keep a terminal available and inspect
patches against the installed Howdy version first.

## Package upgrades

- **Howdy:** `compare.py` is package-managed. Upgrade/reinstall can overwrite the
  dispatch, returning to dlib. Check `howdy-npu check` plus the actual installed
  dispatch. The check reads the configuration but does not by itself prove the
  compare script still contains the patch. Reapply only the reviewed small diff.
- **GNOME Keyring:** private master-password D-Bus API may change. Run the isolated
  integration test after upgrades. The optional helper failing should not deny login.
- **OpenVINO/NPU firmware:** recheck NPU device access and recognition behavior.
- **PAM:** package/config updates may alter GDM layout. Inspect `.pacnew` files;
  never copy old full PAM snapshots over a newer configuration without review.
- **Account/keyring password:** separate credentials; changing the Linux password
  does not intentionally rotate the dedicated secret. Use `restore-password`
  before removing the stored secret/helper.

## Tests and observed verification

- 20 unit tests: face match gating/templates/dispatch, secret permission and symlink
  defenses, pipe-only credential delivery, PAM scope and transformation.
- Isolated integration: disposable daemon/collection on a separate D-Bus session,
  password change, wrong-old rejection, credential verification, lock/wrong-unlock
  rejection, successful unlock, password restoration.
- Live setup: local hidden-input password change; dedicated secret verified using
  same-password change (which really validates credentials even if unlocked).
- Manual session-hook invocation: successful; `Locked=false` on login collection.
- Full new GDM login remains to be tested by the user. No logout/reboot was forced.

`tests/integration_keyring.py` refuses the normal `/run/user/...` session bus,
uses an isolated data directory/control socket, and disables D-Bus auto-activation
while connecting to its test daemon. It never accesses your saved browser secrets.

## Updating project snapshots

Configuration snapshots are nonsecret but system-specific. Refresh copies of
`/etc/howdy/config.ini`, `/etc/pam.d/gdm-password`, `/etc/pam.d/swaylock`, and the
NPU udev rule after reviewed changes. Keep pre-keyring PAM snapshot for auditing.
Never export templates or stored keyring credentials into this project.

See `docs/licenses/HOWDY-LICENSE` for the copied upstream Howdy code. Generic
models have upstream Open Model Zoo documentation and applicable terms; see the
source links in `SYSTEM.md`. GNOME implementation was inspected for compatibility;
its source is not bundled in this project.
