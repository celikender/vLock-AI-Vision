"""Setup page backend: writes API keys and SAM settings to the local .env file.

Secrets go from the browser to this server once and are never sent back: the page only learns
whether each one is set. Values already set in the process environment win over .env and are
reported as such. In Docker the .env file lives on the host, so this page is read-only there.
"""
import os
import re
import threading
from pathlib import Path
from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from services.vlock.transports import MINIMUM_PASSWORD

BACKENDS = ('local', 'meta_api', 'meta_api_video')
TOKEN = re.compile(r'[A-Za-z0-9_.:|+/=-]+')
OPC_USERNAME = re.compile(r'[A-Za-z0-9_.@-]{1,64}')
PASSWORD = re.compile(r'[^\s\'"\\$`]+')
SECRETS = ('META_API_KEY', 'VLOCK_OPCUA_SERVER_PASSWORD', 'VLOCK_API_TOKEN')
PLAIN = {'VLOCK_SAM_BACKEND': 'local', 'VLOCK_SAM_TIMEOUT_MS': '3000', 'VLOCK_SAM_DAILY_LIMIT_USD': '10',
         'VLOCK_OPCUA_SERVER_USERNAME': ''}
LABELS = {'META_API_KEY': 'Meta API key', 'VLOCK_OPCUA_SERVER_PASSWORD': 'OPC UA password',
          'VLOCK_API_TOKEN': 'REST API token', 'VLOCK_SAM_BACKEND': 'SAM engine',
          'VLOCK_SAM_TIMEOUT_MS': 'Request limit', 'VLOCK_SAM_DAILY_LIMIT_USD': 'Daily spending limit',
          'VLOCK_OPCUA_SERVER_USERNAME': 'OPC UA username'}


class SetupError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def meta_client(key, base_url):
    return OpenAI(api_key=key, base_url=base_url, timeout=8, max_retries=0)


def checked(name, value):
    """The value to store, or SetupError naming the field but never echoing the value."""
    if not isinstance(value, str):
        raise SetupError(f'{LABELS[name]}: expected text.')
    value = value.strip()
    if name == 'VLOCK_SAM_BACKEND' and value not in BACKENDS:
        raise SetupError('Choose a SAM engine from the list.')
    if name == 'VLOCK_SAM_TIMEOUT_MS' and not (value.isdigit() and 500 <= int(value) <= 30000):
        raise SetupError('Request limit: 500 to 30000 milliseconds.')
    if name == 'VLOCK_SAM_DAILY_LIMIT_USD' and not (re.fullmatch(r'\d{1,5}(\.\d{1,2})?', value) and 0.01 <= float(value) <= 10000):
        raise SetupError('Daily spending limit: 0.01 to 10000 US dollars.')
    if name == 'VLOCK_OPCUA_SERVER_USERNAME' and value and not OPC_USERNAME.fullmatch(value):
        raise SetupError('OPC UA username: up to 64 letters, digits, dots, hyphens, underscores or @.')
    if name == 'VLOCK_OPCUA_SERVER_PASSWORD' and not (MINIMUM_PASSWORD <= len(value) <= 200 and PASSWORD.fullmatch(value)):
        raise SetupError(f'OPC UA password: {MINIMUM_PASSWORD}-200 characters, without spaces, quotes, $ or backslashes.')
    if name in ('META_API_KEY', 'VLOCK_API_TOKEN') and not (8 <= len(value) <= 500 and TOKEN.fullmatch(value)):
        raise SetupError(f'{LABELS[name]}: this does not look like a key. Paste only the key, with no spaces.')
    return value


class SetupConfig:
    def __init__(self, env_path, active_backend='local', environ=os.environ, client_factory=meta_client):
        self.env_path = Path(env_path)
        self.active_backend = active_backend
        self.environ = environ
        self.client_factory = client_factory
        self.lock = threading.Lock()

    def values(self):
        return {**dotenv_values(self.env_path), **self.environ}

    def view(self):
        saved, overridden = dotenv_values(self.env_path), set(self.environ)
        merged = {**saved, **self.environ}
        fields = {name: dict(set=bool((merged.get(name) or '').strip()), overridden=name in overridden) for name in SECRETS}
        for name, default in PLAIN.items():
            fields[name] = dict(value=(merged.get(name) or default).strip(), overridden=name in overridden)
        backend = fields['VLOCK_SAM_BACKEND']['value']
        return dict(writable=self.environ.get('VLOCK_SAM_EXTERNAL') != '1', fields=fields, activeBackend=self.active_backend,
                    restartNeeded=self.active_backend != 'none' and backend != self.active_backend)

    def save(self, data):
        """Empty secrets keep the saved value. Returns the names changed, for the audit log."""
        if self.environ.get('VLOCK_SAM_EXTERNAL') == '1':
            raise SetupError('In Docker, edit .env on the host and run docker compose up -d.', 409)
        values, clear = data.get('values', {}), data.get('clear', [])
        if not isinstance(values, dict) or not isinstance(clear, list):
            raise SetupError('Invalid setup request.')
        changes = {}
        for name, value in values.items():
            if name not in LABELS:
                raise SetupError('Unknown setup field.')
            if name in SECRETS and value == '':
                continue
            changes[name] = checked(name, value)
        for name in clear:
            if name not in SECRETS:
                raise SetupError('Only saved secrets can be removed.')
            changes[name] = ''
        with self.lock:
            self.write(changes)
        return sorted(changes)

    def write(self, changes):
        """Replace or add single lines, so comments and every other setting stay as they are."""
        lines = self.env_path.read_text(encoding='utf-8').splitlines() if self.env_path.exists() else []
        remaining = dict(changes)
        for index, line in enumerate(lines):
            match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
            if match and match[1] in changes:
                lines[index] = f'{match[1]}={remaining.pop(match[1], changes[match[1]])}'
        lines.extend(f'{name}={value}' for name, value in remaining.items())
        temporary = self.env_path.with_name(self.env_path.name + '.tmp')
        temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        temporary.replace(self.env_path)

    def test_meta(self):
        """Ask Meta which models this key may use. It is free and sends no camera image."""
        values = self.values()
        key = (values.get('META_API_KEY') or values.get('MODEL_API_KEY') or '').strip()
        if not key:
            raise SetupError('Save a Meta API key first.')
        try:
            with self.client_factory(key, values.get('META_BASE_URL') or 'https://api.meta.ai/v1') as client:
                models = {model.id for model in client.models.list().data}
        except APIStatusError as error:
            messages = {401: 'Meta rejected this key.', 402: 'Meta billing is not configured for this key.',
                        403: 'This key has no model access.'}
            raise SetupError(messages.get(error.status_code, f'Meta answered with HTTP {error.status_code}.'), 502) from None
        except (APITimeoutError, APIConnectionError):
            raise SetupError('Cannot reach Meta. Check the internet connection.', 503) from None
        sam, muse = values.get('META_SAM_MODEL') or 'sam-3.1', values.get('META_MUSE_MODEL') or 'muse-spark-1.3'
        return dict(ok=True, sam=sam in models, muse=muse in models, samModel=sam, museModel=muse)
