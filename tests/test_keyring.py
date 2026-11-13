import importlib.util
import os
from pathlib import Path
import pwd
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('keyring_root', ROOT / 'src/keyring/root_helper.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class KeyringHelperTests(unittest.TestCase):
    def metadata(self, **changes):
        values = dict(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_size=12)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_secret_reads_valid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'secret'
            file.write_text('exampletoken')
            with patch.object(helper, 'trusted'), patch.object(helper.os, 'fstat', return_value=self.metadata()):
                self.assertEqual(helper.read_secret(file), 'exampletoken')

    def test_unsafe_secret_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'secret'
            file.write_text('exampletoken')
            for changes in [dict(st_uid=1000), dict(st_mode=stat.S_IFREG | 0o640),
                            dict(st_mode=stat.S_IFIFO | 0o600), dict(st_nlink=2),
                            dict(st_size=0), dict(st_size=5000)]:
                with self.subTest(changes=changes), patch.object(helper, 'trusted'), \
                     patch.object(helper.os, 'fstat', return_value=self.metadata(**changes)):
                    with self.assertRaises(PermissionError):
                        helper.read_secret(file)

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'secret'
            file.write_text('exampletoken')
            link = Path(directory) / 'link'
            link.symlink_to(file)
            with patch.object(helper, 'trusted'):
                with self.assertRaises(OSError):
                    helper.read_secret(link)

    def test_newlines_not_silently_trimmed(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'secret'
            file.write_text('exampletoken\n')
            with patch.object(helper, 'trusted'), patch.object(helper.os, 'fstat', return_value=self.metadata(st_size=13)):
                with self.assertRaises(ValueError):
                    helper.read_secret(file)

    def test_secret_not_in_argv_or_environment(self):
        account = pwd.getpwuid(os.getuid())
        request = {'operation': 'unlock', 'password': 'test-secret-only'}
        with patch.object(helper, 'trusted'), \
             patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            helper.run_worker(account, request)
        args, kwargs = run.call_args
        self.assertNotIn('test-secret-only', repr(args))
        self.assertNotIn('test-secret-only', repr(kwargs['env']))
        self.assertIn(b'test-secret-only', kwargs['input'])
        self.assertEqual(kwargs['user'], account.pw_uid)
        self.assertEqual(kwargs['cwd'], '/')
        self.assertEqual(kwargs['stderr'], helper.subprocess.DEVNULL)
        self.assertIn('-I', args[0])

    def test_worker_failure_is_generic(self):
        account = pwd.getpwuid(os.getuid())
        with patch.object(helper, 'trusted'), \
             patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, 'details suppressed'):
                helper.run_worker(account, {'operation': 'unlock', 'password': 'test'})

    def test_other_account_refused(self):
        with patch.object(helper.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=65534)):
            with self.assertRaises(PermissionError):
                helper.account_for('nobody')

    def test_pam_close_session_is_noop(self):
        with patch.dict(os.environ, {'PAM_TYPE': 'close_session'}, clear=True), \
             patch.object(helper, 'unlock') as unlock:
            helper.pam_session()
            unlock.assert_not_called()

    def test_wrong_pam_service_refused(self):
        with patch.dict(os.environ, {'PAM_TYPE': 'open_session', 'PAM_SERVICE': 'sshd'}, clear=True):
            with self.assertRaises(PermissionError):
                helper.pam_session()


class PamTransformTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('pam_config', ROOT / 'scripts/configure-pam-keyring.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.original = (ROOT / 'config/pam.d/gdm-password.before-keyring').read_text()

    def test_only_session_rules_changed(self):
        updated = self.module.transform(self.original, True)
        auth = lambda text: [line for line in text.splitlines() if line.startswith(('auth', '-auth', 'account', 'password', '-password'))]
        self.assertEqual(auth(updated), auth(self.original))
        self.assertIn(self.module.HOOK, updated)
        self.assertEqual(self.module.transform(updated, False), self.original)

    def test_idempotent(self):
        updated = self.module.transform(self.original, True)
        self.assertEqual(self.module.transform(updated, True), updated)

    def test_unknown_layout_refused(self):
        with self.assertRaises(ValueError):
            self.module.transform('auth include other\n', True)


if __name__ == '__main__':
    unittest.main()
