#!/bin/sh
# Install root-owned code only. Does not change passwords or activate PAM.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo.' >&2; exit 1; }
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install -d -o root -g root -m 755 /usr/local/lib/howdy-keyring
install -d -o root -g root -m 700 /etc/howdy-keyring
install -d -o root -g root -m 755 /var/lib/howdy-keyring
install -d -o root -g root -m 700 /var/lib/howdy-keyring/backup
install -o root -g root -m 644 "$project/src/keyring/root_helper.py" /usr/local/lib/howdy-keyring/root_helper.py
install -o root -g root -m 644 "$project/src/keyring/secret_service.py" /usr/local/lib/howdy-keyring/secret_service.py
install -o root -g root -m 755 "$project/scripts/howdy-keyring" /usr/local/sbin/howdy-keyring
install -o root -g root -m 755 "$project/scripts/howdy-keyring-session" /usr/local/sbin/howdy-keyring-session
install -o root -g root -m 644 "$project/scripts/configure-pam-keyring.py" /usr/local/lib/howdy-keyring/configure_pam.py
install -o root -g root -m 755 "$project/scripts/howdy-keyring-pam" /usr/local/sbin/howdy-keyring-pam
printf 'Code installed. Next: sudo howdy-keyring setup --user <user>\n'
