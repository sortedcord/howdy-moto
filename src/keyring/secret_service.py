"""User-side GNOME Keyring D-Bus operations. Secrets use an anonymous pipe.

The GNOME private master-password API is version-dependent. No secret output.
Only run this worker with the target user's identity, never as root on their bus.
"""
import json
import os
import sys

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

SERVICE = 'org.freedesktop.secrets'
PATH = '/org/freedesktop/secrets'
INTERFACE = 'org.freedesktop.Secret.Service'
PRIVATE = 'org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface'
COLLECTION = 'org.freedesktop.Secret.Collection'


class SecretService:
    def __init__(self, address=None, no_auto_start=False):
        self.flags = Gio.DBusCallFlags.NO_AUTO_START if no_auto_start else Gio.DBusCallFlags.NONE
        address = address or f'unix:path=/run/user/{os.getuid()}/bus'
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        self.bus = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
        response = self.call(PATH, INTERFACE, 'OpenSession',
                             GLib.Variant('(sv)', ('plain', GLib.Variant('s', ''))), '(vo)')
        _, self.session = response.unpack()

    def call(self, path, interface, method, args, result='()'):
        return self.bus.call_sync(SERVICE, path, interface, method, args,
                                  GLib.VariantType.new(result), self.flags,
                                  5000, None)

    def secret(self, password):
        return (self.session, b'', password.encode('utf-8'), 'text/plain')

    def login(self):
        path, = self.call(PATH, INTERFACE, 'ReadAlias', GLib.Variant('(s)', ('login',)), '(o)').unpack()
        if path == '/':
            raise RuntimeError('No login keyring')
        return path

    def locked(self, path):
        value, = self.call(path, 'org.freedesktop.DBus.Properties', 'Get',
                           GLib.Variant('(ss)', (COLLECTION, 'Locked')), '(v)').unpack()
        return bool(value)

    def unlock(self, path, password):
        self.call(PATH, PRIVATE, 'UnlockWithMasterPassword',
                  GLib.Variant('(o(oayays))', (path, self.secret(password))))
        if self.locked(path):
            raise RuntimeError('Keyring remains locked')

    def change(self, path, old, new):
        self.call(PATH, PRIVATE, 'ChangeWithMasterPassword',
                  GLib.Variant('(o(oayays)(oayays))', (path, self.secret(old), self.secret(new))))


def main():
    if os.geteuid() == 0:
        raise PermissionError('Worker must run as the target user')
    request = json.loads(sys.stdin.buffer.read(32768))
    service = SecretService()
    path = service.login()
    if request['operation'] == 'change':
        service.change(path, request['old'], request['new'])
        # ChangeWithMasterPassword verifies the old password. Explicitly verify new.
        service.unlock(path, request['new'])
    elif request['operation'] == 'verify':
        # UnlockWithMasterPassword short-circuits on unlocked collections.
        # A same-password change really verifies the supplied credential.
        service.change(path, request['password'], request['password'])
    elif request['operation'] == 'unlock':
        service.unlock(path, request['password'])
    else:
        raise ValueError('Unsupported operation')
    print('OK')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never log exceptions or requests; upstream errors might contain data.
        print('Keyring operation failed (details suppressed).', file=sys.stderr)
        sys.exit(1)
