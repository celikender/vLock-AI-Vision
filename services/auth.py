"""Local users, roles, sessions and the audit log for the web application.

Roles: viewer (read everything), operator (camera connect, monitoring on/off, SAM restart),
admin (configuration, Muse, integrations, users, OPC UA client trust). Passwords are stored
as PBKDF2-SHA256 hashes in <data>/users.json; sessions live in memory (a restart logs out).
Every login, permission refusal and change is appended to <data>/audit.log.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

ROLES = ('viewer', 'operator', 'admin')
USERNAME = re.compile(r'[A-Za-z0-9_.-]{3,32}')
MINIMUM_PASSWORD = 10
ITERATIONS = 310_000
IDLE_SECONDS = 8 * 3600
MAX_SECONDS = 24 * 3600
LOCKOUT = (5, 300)  # five failed logins within five minutes lock that username for five minutes
AUDIT_LIMIT = 5 * 1024 * 1024


class AuthError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def rank(role):
    return ROLES.index(role) if role in ROLES else -1


def digest(password, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), iterations).hex()


class Auth:
    def __init__(self, directory, clock=time.time):
        self.directory = Path(directory)
        self.path = self.directory / 'users.json'
        self.audit_path = self.directory / 'audit.log'
        self.clock = clock
        self.lock = threading.RLock()
        self.sessions = {}
        self.failures = {}
        # Compared against when a username does not exist, so timing does not reveal it.
        self.dummy = dict(salt=secrets.token_hex(16), iterations=ITERATIONS)
        self.dummy['hash'] = digest(secrets.token_hex(8), self.dummy['salt'])

    # Users -----------------------------------------------------------------
    def users(self):
        with self.lock:
            if not self.path.exists():
                return {}
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}

    def save_users(self, users):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(users, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def setup_needed(self):
        return not self.users()

    def public_users(self):
        return [dict(username=name, role=user['role'], created=user.get('created')) for name, user in sorted(self.users().items())]

    @staticmethod
    def check_password(password):
        if not isinstance(password, str) or not MINIMUM_PASSWORD <= len(password) <= 200:
            raise AuthError(f'Use a password of {MINIMUM_PASSWORD}-200 characters.')

    def create_user(self, actor, username, password, role):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise AuthError('Username: 3-32 letters, digits, dots, hyphens or underscores.')
        if role not in ROLES:
            raise AuthError('Choose a role: viewer, operator or admin.')
        self.check_password(password)
        with self.lock:
            users = self.users()
            if username.lower() in {name.lower() for name in users}:
                raise AuthError('That username already exists.', 409)
            salt = secrets.token_hex(16)
            users[username] = dict(role=role, salt=salt, iterations=ITERATIONS, hash=digest(password, salt),
                                   created=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.clock())))
            self.save_users(users)
        self.audit(actor, 'user.create', username, detail=f'role {role}')
        return self.public_users()

    def create_first_admin(self, username, password):
        """The check and the write are one step, so two setup requests cannot both create an admin."""
        with self.lock:
            if not self.setup_needed():
                raise AuthError('Setup is already done. Log in instead.', 409)
            return self.create_user(dict(user='setup', role=''), username, password, 'admin')

    def delete_user(self, actor, username):
        with self.lock:
            users = self.users()
            if username not in users:
                raise AuthError('No such user.', 404)
            if users[username]['role'] == 'admin' and sum(u['role'] == 'admin' for u in users.values()) == 1:
                raise AuthError('Keep at least one admin.', 409)
            del users[username]
            self.save_users(users)
            self.sessions = {token: s for token, s in self.sessions.items() if s['user'] != username}
        self.audit(actor, 'user.delete', username)
        return self.public_users()

    def set_password(self, actor, username, password):
        self.check_password(password)
        with self.lock:
            users = self.users()
            if username not in users:
                raise AuthError('No such user.', 404)
            salt = secrets.token_hex(16)
            users[username].update(salt=salt, iterations=ITERATIONS, hash=digest(password, salt))
            self.save_users(users)
            # Other sessions of that user end; a changed password must not leave old logins open.
            self.sessions = {token: s for token, s in self.sessions.items()
                             if s['user'] != username or (actor and token == actor.get('token'))}
        self.audit(actor, 'user.password', username)

    # Sessions --------------------------------------------------------------
    def login(self, username, password, client=''):
        now = self.clock()
        key = str(username).lower()[:64]
        with self.lock:
            recent = [t for t in self.failures.get(key, []) if now - t < LOCKOUT[1]]
            self.failures[key] = recent
            if len(recent) >= LOCKOUT[0]:
                self.audit(dict(user=key, role=''), 'login', key, 'refused', 'locked after repeated failures')
                raise AuthError('Too many failed logins. Wait five minutes and try again.', 429)
            user = self.users().get(username) if isinstance(username, str) else None
            stored = user or self.dummy
            supplied = digest(password if isinstance(password, str) else '', stored['salt'], stored.get('iterations', ITERATIONS))
            if user is None or not hmac.compare_digest(supplied, stored['hash']):
                recent.append(now)
                self.audit(dict(user=key, role=''), 'login', key, 'refused', 'wrong username or password ' + client)
                raise AuthError('Wrong username or password.', 401)
            self.failures.pop(key, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = dict(user=username, role=user['role'], started=now, seen=now)
        self.audit(dict(user=username, role=user['role']), 'login', username)
        return token

    def session(self, token):
        if not isinstance(token, str) or not token:
            return None
        now = self.clock()
        with self.lock:
            current = self.sessions.get(token)
            if current is None:
                return None
            if now - current['seen'] > IDLE_SECONDS or now - current['started'] > MAX_SECONDS:
                del self.sessions[token]
                return None
            # The role is read again so a changed or deleted user takes effect at once.
            user = self.users().get(current['user'])
            if user is None:
                del self.sessions[token]
                return None
            current.update(seen=now, role=user['role'])
            return dict(current, token=token)

    def logout(self, token):
        with self.lock:
            current = self.sessions.pop(token, None)
        if current:
            self.audit(current, 'logout', current['user'])

    # Audit -----------------------------------------------------------------
    def audit(self, actor, action, target='', result='ok', detail=''):
        entry = dict(time=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.clock())),
                     user=(actor or {}).get('user', 'system'), role=(actor or {}).get('role', ''),
                     action=action, target=str(target)[:120], result=result, detail=str(detail)[:300])
        try:
            with self.lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                if self.audit_path.exists() and self.audit_path.stat().st_size > AUDIT_LIMIT:
                    self.audit_path.replace(self.audit_path.with_name('audit.log.1'))
                with self.audit_path.open('a', encoding='utf-8') as file:
                    file.write(json.dumps(entry) + '\n')
        except OSError:
            pass  # Auditing must never block the application.
        return entry

    def audit_tail(self, limit=200):
        try:
            lines = self.audit_path.read_text(encoding='utf-8').splitlines()[-limit:]
        except OSError:
            return []
        rows = []
        for line in reversed(lines):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows
