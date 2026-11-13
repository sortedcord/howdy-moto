"""Add/remove only the optional GDM keyring session hook; never edit auth rules."""
import argparse
import os
from pathlib import Path
import stat
import tempfile

PAM = Path('/etc/pam.d/gdm-password')
BACKUP = Path('/var/lib/howdy-keyring/backup/gdm-password.before-keyring')
COMMENT = '# Local root-stored dedicated keyring secret; session-only, never authenticates.\n'
HOOK = '-session   optional                    pam_exec.so quiet type=open_session seteuid /usr/local/sbin/howdy-keyring-session\n'
ANCHOR = '-session   optional                    pam_oo7.so auto_start\n'


def transform(content, enable):
    if enable:
        if HOOK in content:
            return content
        if content.count(ANCHOR) != 1:
            raise ValueError('Unexpected PAM layout; manual review required')
        if '/usr/local/sbin/howdy-keyring-session' in content:
            raise ValueError('Existing nonstandard hook; manual review required')
        return content.replace(ANCHOR, ANCHOR + COMMENT + HOOK)
    return content.replace(COMMENT + HOOK, '').replace(HOOK, '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['enable', 'disable'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo')
    info = PAM.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError('Unexpected PAM file permissions')
    content = PAM.read_text()
    updated = transform(content, args.action == 'enable')
    if args.action == 'enable':
        # Never activate without a configured secret. Read no secret contents.
        secret = Path('/etc/howdy-keyring/1000.secret').lstat()
        if secret.st_uid != 0 or stat.S_IMODE(secret.st_mode) != 0o600:
            raise PermissionError('Dedicated keyring secret not configured safely')
        if not BACKUP.exists():
            with BACKUP.open('x') as output:
                os.chmod(BACKUP, 0o600)
                output.write(content)
    fd, temporary = tempfile.mkstemp(dir=PAM.parent, prefix='.gdm-keyring-')
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, PAM)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Optional keyring session hook', args.action + 'd; authentication rules unchanged.')


if __name__ == '__main__':
    main()
