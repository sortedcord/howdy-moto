# Dedicated locally stored keyring password

## Purpose and security trade-off

Face recognition authenticates an account but cannot reconstruct its password.
GNOME Keyring normally uses the typed login password to decrypt `login.keyring`.
This integration gives the keyring a separate, high-entropy random password,
stores that password root-only, and unlocks it after a successful GDM session.
The Linux account password is never stored and is not changed.

**The stored keyring password is plaintext.** Mode 600 is access control, not
encryption. This system has no observed root-disk encryption. Offline SSD access
or root compromise can expose both the password and keyring. A false face
acceptance also grants access to an unlocked keyring. The user explicitly
accepted this trade-off. Do not describe it as TPM protection.

No password is accepted in argv/environment, printed, logged, copied into this
project, or sent through chat. Setup takes the existing password only in a local
TTY with echo disabled. It exists transiently in process memory and an anonymous
pipe. Python does not guarantee complete memory zeroization. Core dumps are
disabled for the root helper and its child. The user-side worker uses a local
Secret Service `plain` D-Bus session, not an encrypted DH transport; the user
service necessarily receives the keyring password.

## Components

- `src/keyring/root_helper.py`: root-only setup/unlock/restore/PAM session logic.
- `src/keyring/secret_service.py`: privilege-dropped user-side D-Bus worker.
- `scripts/configure-pam-keyring.py`: add/remove only the optional GDM session hook.
- `/usr/local/lib/howdy-keyring/`: installed root-owned code; Python uses `-I`.
- `/usr/local/sbin/howdy-keyring`: admin command; not setuid and has no sudoers grant.
- `/usr/local/sbin/howdy-keyring-session`: optional PAM session entry point.
- `/usr/local/sbin/howdy-keyring-pam`: enable/disable the optional hook.
- `/etc/howdy-keyring/1000.secret`: dedicated keyring password; root:root 600,
  containing directory root:root 700. Never print/copy it into this repository.
- `/etc/howdy-keyring/1000.pending`: crash-recovery secret during setup, same permissions.
- `/var/lib/howdy-keyring/backup/`: root-only encrypted keyring/PAM backups.
- `/var/lib/howdy-keyring/status.json`: nonsecret setup stage only.

The helper is restricted to UID 1000 (`<user>`). The root helper validates
root-controlled paths, rejects symlinks/unsafe secret modes, and launches a fixed
root-owned worker as the user's UID/GID/groups, with a minimal environment.
Secrets travel through stdin only, not shell expansion. Worker output/errors are
suppressed. Session failures have a 10-second hard cap and cannot deny login.

## Login flow

1. Existing GDM account restrictions and Howdy/password authentication run unchanged.
2. Existing PAM session initialization and GNOME Keyring startup run.
3. An **optional session-only** `pam_exec.so` hook invokes the root helper.
4. It reads the dedicated secret, drops child privileges to the authenticated user,
   connects to that user's bus, and unlocks their login collection.
5. Failure leaves the ordinary browser keyring prompt available; authentication
   is not changed and the helper never returns an authentication success decision.

No hook is added to swaylock, sudo, or SSH. Screen unlock normally retains the
already unlocked keyring. A manually re-locked keyring is not automatically
unlocked by swaylock. Every successfully authenticated GDM login (including a
password login) is eligible, not only Howdy logins.

GNOME's `InternalUnsupportedGuiltRiddenInterface` password API is private and may
change after upgrades. Test before relying on a new GNOME Keyring version.
`UnlockWithMasterPassword` can return success on an already-unlocked collection
without verifying the supplied password; recovery therefore uses a same-password
change to actually verify a pending credential.

## Install / configure

```
cd ~/Projects/howdy-moto
python -m unittest discover -s tests -p 'test_*.py'
dbus-run-session -- python tests/integration_keyring.py
sudo sh scripts/install-keyring.sh
sudo howdy-keyring setup --user <user>
sudo howdy-keyring-pam enable
```

Setup prompts locally for the **current login keyring password**, then generates
a separate random password. It backs up the encrypted keyring before changing its
password. Existing saved items remain. Do not rerun setup after it succeeds.

Unlock without revealing the stored secret:

```
sudo howdy-keyring unlock --user <user>
```

The PAM path is exercised manually without a real login by:

```
sudo env PAM_TYPE=open_session PAM_SERVICE=gdm-password PAM_USER=<user> \
  /usr/local/sbin/howdy-keyring-session
```

This only exercises the helper in a current session; the full next-login timing
must still be checked with a real GDM login. Keep a working terminal available.

## Recovery / rollback

**Do not delete the secret or revert old keyring files as the first step.** The
keyring's master password was changed. Old encrypted backups may lack newer items.

To return to a manually known keyring password:

```
sudo howdy-keyring restore-password --user <user>
```

Enter a new keyring password twice in the hidden local prompts. Use your account
password if you want standard password-login automatic unlocking again. This
changes the live keyring password while preserving items and removes the stored
random secret only after success. It does not alter your Linux account password.

Then remove the optional session hook:

```
sudo howdy-keyring-pam disable
```

Face authentication stays enabled. To restore the old CPU/dlib Howdy separately:

```
sudo howdy-npu-rollback
```

NPU rollback restores the original Howdy config and compare script only. It leaves
the current GDM PAM session hook and dedicated keyring password intact. Thus the
keyring helper can continue with dlib/password logins. If removing the keyring
helper separately, restore a known keyring password FIRST, or retain the secret
and use `howdy-keyring unlock` manually.

If setup was interrupted, retain `1000.pending` and rerun setup in a local TTY.
It verifies whether the pending secret already became the keyring password before
asking for the old password again. No secret is discarded on an uncertain result.

## Troubleshooting

- `journalctl -b -t howdy-keyring`: generic success/failure messages only.
- Helper failure: verify `/run/user/1000/bus` exists and GNOME Keyring owns
  `org.freedesktop.secrets`; run the admin `unlock` command.
- Dedicated password differs from your Linux password: native keyring PAM may
  report a failed password unlock before this optional session helper succeeds.
- Changing your Linux account password does not intentionally rotate this separate
  keyring password. Keep the local secret and keyring in sync using these tools.
- Never commit any file from `/etc/howdy-keyring/`, personal enrollment directories,
  `~/.local/share/keyrings/`, or private backups.
