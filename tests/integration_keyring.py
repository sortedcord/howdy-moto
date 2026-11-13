"""Run ONLY inside a fresh dbus-run-session; never touches the real keyring."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('secret_service', ROOT / 'src/keyring/secret_service.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
GLib = module.GLib


def main():
    address = os.environ['DBUS_SESSION_BUS_ADDRESS']
    if '/run/user/' in address or not address.startswith('unix:path=/tmp/'):
        raise RuntimeError('Refusing a non-isolated session bus')
    with tempfile.TemporaryDirectory(prefix='howdy-keyring-test-') as temporary:
        base = Path(temporary)
        runtime = base / 'run'
        runtime.mkdir(mode=0o700)
        control = runtime / 'keyring'
        control.mkdir(mode=0o700)
        env = dict(os.environ, HOME=str(base), XDG_DATA_HOME=str(base / 'data'),
                   XDG_CONFIG_HOME=str(base / 'config'), XDG_RUNTIME_DIR=str(runtime))
        env.pop('GNOME_KEYRING_CONTROL', None)
        daemon = subprocess.Popen(['/usr/bin/gnome-keyring-daemon', '--foreground',
                                   '--components=secrets', '--control-directory', str(control)],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            service = None
            for _ in range(30):
                try:
                    service = module.SecretService(address, no_auto_start=True)
                    break
                except Exception:
                    time.sleep(0.1)
            if service is None:
                raise RuntimeError('Isolated keyring daemon did not start')
            old, new = 'test-original-not-a-real-secret', 'test-replacement-not-a-real-secret'
            properties = {module.COLLECTION + '.Label': GLib.Variant('s', 'Disposable test')}
            path, = service.call(module.PATH, module.PRIVATE, 'CreateWithMasterPassword',
                                  GLib.Variant('(a{sv}(oayays))',
                                               (properties, service.secret(old))), '(o)').unpack()
            service.call(module.PATH, module.INTERFACE, 'SetAlias',
                         GLib.Variant('(so)', ('default', path)))
            assert service.call(module.PATH, module.INTERFACE, 'ReadAlias',
                                GLib.Variant('(s)', ('default',)), '(o)').unpack() == (path,)
            service.change(path, old, new)
            try:
                # Must reject the old credential even while collection is unlocked.
                service.change(path, old, old)
            except Exception:
                pass
            else:
                raise AssertionError('Incorrect old password accepted')
            service.change(path, new, new)
            service.call(module.PATH, module.INTERFACE, 'Lock',
                         GLib.Variant('(ao)', ([path],)), '(aoo)')
            assert service.locked(path)
            try:
                service.unlock(path, old)
            except Exception:
                pass
            else:
                raise AssertionError('Wrong unlock password accepted')
            assert service.locked(path)
            service.unlock(path, new)
            assert not service.locked(path)
            service.change(path, new, old)  # Test password restoration as well.
            print('PASS: isolated create/change/reject-old/verify/lock/reject-wrong/unlock/restore')
        finally:
            daemon.terminate()
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()


if __name__ == '__main__':
    main()
