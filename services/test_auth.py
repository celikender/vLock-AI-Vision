"""Users, sessions, lockout and audit for the web application."""
import json
import tempfile
import unittest
from pathlib import Path

from services.auth import Auth, AuthError, IDLE_SECONDS


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.auth = Auth(self.directory.name, clock=lambda: self.now[0])
        self.auth.create_user(None, 'admin', 'admin-password-1', 'admin')

    def tearDown(self):
        self.directory.cleanup()

    def test_passwords_are_hashed_and_checked(self):
        stored = (Path(self.directory.name) / 'users.json').read_text(encoding='utf-8')
        self.assertNotIn('admin-password-1', stored)
        self.assertEqual(json.loads(stored)['admin']['iterations'], 310_000)
        token = self.auth.login('admin', 'admin-password-1')
        self.assertEqual(self.auth.session(token)['role'], 'admin')
        for username, password in [('admin', 'wrong-password'), ('nobody', 'admin-password-1')]:
            with self.assertRaises(AuthError) as caught:
                self.auth.login(username, password)
            self.assertEqual(caught.exception.status, 401)
        for bad in [('ab', 'long-enough-pw', 'viewer'), ('valid-name', 'short', 'viewer'), ('valid-name', 'long-enough-pw', 'root')]:
            with self.subTest(bad=bad), self.assertRaises(AuthError):
                self.auth.create_user(None, *bad)

    def test_repeated_failures_lock_the_username(self):
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.auth.login('admin', 'wrong-password')
        with self.assertRaises(AuthError) as caught:
            self.auth.login('admin', 'admin-password-1')
        self.assertEqual(caught.exception.status, 429)
        self.now[0] += 301
        self.assertTrue(self.auth.login('admin', 'admin-password-1'))

    def test_sessions_expire_and_follow_user_changes(self):
        token = self.auth.login('admin', 'admin-password-1')
        self.auth.create_user(None, 'oper', 'operator-pass-1', 'operator')
        operator = self.auth.login('oper', 'operator-pass-1')
        self.assertEqual(self.auth.session(operator)['role'], 'operator')
        self.auth.delete_user(self.auth.session(token), 'oper')
        self.assertIsNone(self.auth.session(operator), 'A deleted user is logged out at once')
        with self.assertRaises(AuthError):
            self.auth.delete_user(self.auth.session(token), 'admin')
        self.now[0] += IDLE_SECONDS + 1
        self.assertIsNone(self.auth.session(token), 'Idle sessions expire')

    def test_password_change_ends_other_sessions(self):
        first = self.auth.login('admin', 'admin-password-1')
        second = self.auth.login('admin', 'admin-password-1')
        self.auth.set_password(self.auth.session(first), 'admin', 'new-password-22')
        self.assertIsNotNone(self.auth.session(first))
        self.assertIsNone(self.auth.session(second))
        with self.assertRaises(AuthError):
            self.auth.login('admin', 'admin-password-1')

    def test_audit_records_actions_without_passwords(self):
        self.auth.login('admin', 'admin-password-1')
        with self.assertRaises(AuthError):
            self.auth.login('admin', 'wrong-password')
        entries = self.auth.audit_tail()
        self.assertEqual([(e['action'], e['result']) for e in entries[:3]],
                         [('login', 'refused'), ('login', 'ok'), ('user.create', 'ok')])
        text = (Path(self.directory.name) / 'audit.log').read_text(encoding='utf-8')
        self.assertNotIn('admin-password-1', text)
        self.assertNotIn('wrong-password', text)


if __name__ == '__main__':
    unittest.main()
