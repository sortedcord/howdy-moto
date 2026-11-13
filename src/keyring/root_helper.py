"""Root-only local keyring-secret storage and optional PAM session unlock.

This deliberately stores a plaintext KEYRING password, never an account password.
No secret is accepted in argv/environment or printed. No setuid/sudoers rule.
"""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import pwd
import resource
import secrets
import signal
import stat
import subprocess
import sys
import syslog
import tempfile
import time

ALLOWED_UID = 1000
PRIVATE_DIR = Path('/etc/howdy-keyring')
STATE_DIR = Path('/var/lib/howdy-keyring')
WORKER = Path('/usr/local/lib/howdy-keyring/secret_service.py')
SECRET_FILE = PRIVATE_DIR / '1000.secret'
PENDING_FILE = PRIVATE_DIR / '1000.pending'
STATUS_FILE = STATE_DIR / 'status.json'


def trusted(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Untrusted root-controlled path')
    return path


def read_secret(path):
    trusted(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                info.st_mode & 0o077 or info.st_nlink != 1 or not 1 <= info.st_size <= 4096):
            raise PermissionError('Unsafe secret-file ownership, mode, or size')
        value = source.read(4097)
    # Generated token has no newline; refuse corruption rather than trim it.
    text = value.decode('ascii')
    if not text or any(c.isspace() for c in text):
        raise ValueError('Invalid stored secret')
    return text


def atomic_write(path, data, mode=0o600):
    trusted(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.new-')
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def status(stage):
    atomic_write(STATUS_FILE, json.dumps({'stage': stage, 'uid': ALLOWED_UID,
                 'updated': time.time()}).encode(), mode=0o644)


def account_for(user):
    account = pwd.getpwnam(user)
    if account.pw_uid != ALLOWED_UID:
        raise PermissionError('Not configured for this account')
    return account


def run_worker(account, request):
    trusted(WORKER)
    runtime = Path(f'/run/user/{account.pw_uid}')
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid:
        raise PermissionError('Invalid user runtime directory')
    # Do not inherit root/PAM environment, loader paths, or Python settings.
    env = {'HOME': account.pw_dir, 'USER': account.pw_name, 'LOGNAME': account.pw_name,
           'PATH': '/usr/bin', 'LANG': 'C.UTF-8', 'XDG_RUNTIME_DIR': str(runtime),
           'DBUS_SESSION_BUS_ADDRESS': f'unix:path={runtime}/bus'}
    result = subprocess.run(
        ['/usr/bin/python', '-I', str(WORKER)], input=json.dumps(request).encode(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=9,
        user=account.pw_uid, group=account.pw_gid,
        extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
        env=env, cwd='/', umask=0o077, close_fds=True,
    )
    if result.returncode:
        raise RuntimeError('User-side keyring operation failed; details suppressed')


def backup_keyring(account):
    source = Path(account.pw_dir) / '.local/share/keyrings/login.keyring'
    destination = trusted(STATE_DIR / 'backup') / (
        'login-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.keyring')
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as inp:
        info = os.fstat(inp.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != account.pw_uid or info.st_size > 10_000_000:
            raise PermissionError('Unexpected login-keyring backup source')
        atomic_write(destination, inp.read(10_000_001))


def setup(account):
    if not sys.stdin.isatty():
        raise RuntimeError('Setup requires a local interactive terminal')
    if SECRET_FILE.exists():
        raise RuntimeError('Already configured; use unlock or restore-password')
    print('HOWDY KEYRING SETUP\n')
    print('This creates a dedicated random keyring password and saves it root-only.')
    print('It does NOT change or store your Linux account password.')
    print('Your unencrypted disk does not protect this secret from offline access.')
    print('No password will be printed. Do not paste it into chat.\n')
    status('waiting-for-local-password')
    if PENDING_FILE.exists():
        new = read_secret(PENDING_FILE)
        try:
            run_worker(account, {'operation': 'verify', 'password': new})
        except Exception:
            pass
        else:
            os.replace(PENDING_FILE, SECRET_FILE)
            status('secret-configured')
            print('Recovered a previously changed keyring; secret is configured.')
            return
    else:
        new = secrets.token_urlsafe(48)
        atomic_write(PENDING_FILE, new.encode('ascii'))
    old = getpass.getpass('Current LOGIN KEYRING password (hidden): ')
    if not old:
        raise ValueError('Empty input refused; no password change attempted')
    backup_keyring(account)
    status('changing-keyring-password')
    run_worker(account, {'operation': 'change', 'old': old, 'new': new})
    del old
    os.replace(PENDING_FILE, SECRET_FILE)
    status('secret-configured')
    print('\nSUCCESS: dedicated keyring password saved root-only; keyring unlocked.')
    print('Linux account password and saved keyring items were not changed.')


def unlock(account):
    value = read_secret(SECRET_FILE)
    run_worker(account, {'operation': 'unlock', 'password': value})


def pam_session():
    # Only the root-run GDM open_session path is supported. This is not an
    # authentication module and must never make an authentication decision.
    if os.environ.get('PAM_TYPE') != 'open_session':
        return
    if os.environ.get('PAM_SERVICE') != 'gdm-password':
        raise PermissionError('Unsupported PAM service')
    account = account_for(os.environ.get('PAM_USER', ''))
    if not SECRET_FILE.exists():
        return
    # PAM/systemd user-bus startup can be asynchronous. Bounded retries; no prompt.
    for attempt in range(3):
        try:
            unlock(account)
            syslog.syslog(syslog.LOG_INFO, 'Login keyring unlocked after authenticated GDM session')
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.5)


def restore_password(account):
    if not sys.stdin.isatty():
        raise RuntimeError('Restore requires a local interactive terminal')
    print('Set a new manually known LOGIN KEYRING password.')
    print('Use your account password if you want normal password-login unlocking.')
    new = getpass.getpass('New keyring password (hidden): ')
    repeated = getpass.getpass('Repeat new keyring password (hidden): ')
    if not new or new != repeated:
        raise ValueError('Passwords do not match or are empty')
    old = read_secret(SECRET_FILE)
    backup_keyring(account)
    run_worker(account, {'operation': 'change', 'old': old, 'new': new})
    # Remove only the locally stored random secret. The keyring/items remain.
    SECRET_FILE.unlink()
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()
    status('restored-manual-keyring-password')
    print('Keyring password changed; locally stored secret removed.')
    print('The optional PAM helper now does nothing; it can be removed separately.')


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo; no privilege escalation is installed')
    syslog.openlog('howdy-keyring', syslog.LOG_PID, syslog.LOG_AUTHPRIV)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'unlock', 'restore-password', 'pam-session'])
    parser.add_argument('--user', default='sortedcord')
    args = parser.parse_args()
    trusted(PRIVATE_DIR)
    trusted(STATE_DIR)
    if args.command == 'pam-session':
        def timeout(*_):
            raise TimeoutError('Session helper time limit')
        signal.signal(signal.SIGALRM, timeout)
        signal.alarm(10)
        pam_session()
        signal.alarm(0)
    else:
        account = account_for(args.user)
        if args.command == 'setup':
            setup(account)
        elif args.command == 'unlock':
            unlock(account)
            print('Login keyring is unlocked.')
        elif args.command == 'restore-password':
            restore_password(account)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Do not interpolate exception text: secrets must never reach journal/UI.
        syslog.syslog(syslog.LOG_ERR, 'Keyring helper failed; details suppressed; password prompt remains available')
        print('Keyring helper failed. No secret details logged. Retry setup or see recovery docs.', file=sys.stderr)
        sys.exit(1)
