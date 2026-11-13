#!/bin/sh
# Nonsecret, non-camera checks. Does not read credentials or personal templates.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
/usr/local/sbin/howdy-npu check --user "$(id -un)"
if grep -Fq "'/usr/local/lib/howdy-npu/backend.py'" /usr/lib/howdy/compare.py; then
    echo 'Howdy compare NPU dispatch: present'
else
    echo 'WARNING: Howdy compare dispatch missing (possible package upgrade)' >&2
    exit 1
fi
if grep -Fq 'pam_exec.so quiet type=open_session seteuid /usr/local/sbin/howdy-keyring-session' /etc/pam.d/gdm-password; then
    echo 'Optional GDM keyring session hook: present'
else
    echo 'GDM keyring session hook: not enabled'
fi
for script in root_helper.py secret_service.py; do
    cmp "$project/src/keyring/$script" "/usr/local/lib/howdy-keyring/$script"
done
cmp "$project/src/npu/backend.py" /usr/local/lib/howdy-npu/backend.py
cmp "$project/scripts/configure-pam-keyring.py" /usr/local/lib/howdy-keyring/configure_pam.py
printf 'Project/runtime code: matches\n'
busctl --user get-property org.freedesktop.secrets /org/freedesktop/secrets/collection/login org.freedesktop.Secret.Collection Locked
printf 'No camera opened; no secret contents read or printed.\n'
