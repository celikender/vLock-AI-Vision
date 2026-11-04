"""Setup page backend: writes .env safely, never returns a secret, rejects bad values."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError

from services.setup_config import SetupConfig, SetupError

KEY = 'fake-test-key-value-123'


class Client:
    def __init__(self, ids=('sam-3.1', 'muse-spark-1.3'), error=None):
        self.ids, self.error = ids, error
        self.models = SimpleNamespace(list=self.list)

    def list(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(id=name) for name in self.ids])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SetupConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'.env'
        self.environ = {}
        self.setup = SetupConfig(self.path, environ=self.environ)

    def test_view_never_contains_a_secret(self):
        self.setup.save(dict(values=dict(META_API_KEY=KEY, VLOCK_API_TOKEN='token-value-123', VLOCK_OPCUA_SERVER_PASSWORD='password-value-1')))
        view = self.setup.view()
        self.assertEqual(view['fields']['META_API_KEY'], dict(set=True, overridden=False))
        for secret in (KEY, 'token-value-123', 'password-value-1'):
            self.assertNotIn(secret, str(view))
        self.assertFalse(view['fields']['VLOCK_API_TOKEN'] == dict(set=False, overridden=False))

    def test_writing_keeps_comments_and_other_settings_and_round_trips(self):
        self.path.write_text('# My comment\nMETA_BASE_URL=https://example.test/v1\nMETA_API_KEY=old\nexport VLOCK_API_TOKEN=keep-this-token\n', encoding='utf-8')
        changed = self.setup.save(dict(values=dict(META_API_KEY=KEY, VLOCK_SAM_BACKEND='meta_api', VLOCK_OPCUA_SERVER_PASSWORD='pass#word-12345')))
        self.assertEqual(changed, ['META_API_KEY', 'VLOCK_OPCUA_SERVER_PASSWORD', 'VLOCK_SAM_BACKEND'])
        text = self.path.read_text(encoding='utf-8')
        self.assertIn('# My comment', text)
        values = dotenv_values(self.path)
        self.assertEqual(values['META_API_KEY'], KEY)
        self.assertEqual(values['META_BASE_URL'], 'https://example.test/v1')
        self.assertEqual(values['VLOCK_API_TOKEN'], 'keep-this-token')
        self.assertEqual(values['VLOCK_SAM_BACKEND'], 'meta_api')
        self.assertEqual(values['VLOCK_OPCUA_SERVER_PASSWORD'], 'pass#word-12345')
        self.assertFalse(self.path.with_name('.env.tmp').exists())

    def test_empty_secret_keeps_the_saved_value_and_clear_removes_it(self):
        self.setup.save(dict(values=dict(META_API_KEY=KEY)))
        self.setup.save(dict(values=dict(META_API_KEY='', VLOCK_SAM_BACKEND='local')))
        self.assertEqual(dotenv_values(self.path)['META_API_KEY'], KEY)
        self.setup.save(dict(clear=['META_API_KEY']))
        self.assertFalse(self.setup.view()['fields']['META_API_KEY']['set'])

    def test_bad_values_are_refused_without_echoing_them_and_nothing_is_written(self):
        bad = [dict(VLOCK_SAM_BACKEND=KEY), dict(VLOCK_SAM_TIMEOUT_MS='soon'), dict(VLOCK_SAM_TIMEOUT_MS='100'),
               dict(META_API_KEY='has a space in-it'), dict(META_API_KEY='short'), dict(META_API_KEY='line\nINJECTED=1'),
               dict(VLOCK_OPCUA_SERVER_PASSWORD='too-short'), dict(VLOCK_OPCUA_SERVER_PASSWORD='has "quotes" inside it'),
               dict(VLOCK_OPCUA_SERVER_USERNAME='no spaces allowed'), dict(OTHER_SETTING='value'), dict(META_API_KEY=5)]
        for values in bad:
            with self.subTest(values=values), self.assertRaises(SetupError) as caught:
                self.setup.save(dict(values=values))
            self.assertNotIn(KEY, str(caught.exception))
        with self.assertRaises(SetupError):
            self.setup.save(dict(clear=['VLOCK_SAM_BACKEND']))
        self.assertFalse(self.path.exists())

    def test_one_bad_field_writes_nothing(self):
        with self.assertRaises(SetupError):
            self.setup.save(dict(values=dict(META_API_KEY=KEY, VLOCK_SAM_TIMEOUT_MS='soon')))
        self.assertFalse(self.path.exists())

    def test_restart_needed_only_when_the_saved_engine_differs(self):
        setup = SetupConfig(self.path, active_backend='local', environ=self.environ)
        self.assertFalse(setup.view()['restartNeeded'])
        setup.save(dict(values=dict(VLOCK_SAM_BACKEND='meta_api')))
        self.assertTrue(setup.view()['restartNeeded'])
        self.assertFalse(SetupConfig(self.path, active_backend='meta_api', environ=self.environ).view()['restartNeeded'])

    def test_environment_value_wins_and_is_reported(self):
        self.environ['META_API_KEY'] = KEY
        view = self.setup.view()
        self.assertEqual(view['fields']['META_API_KEY'], dict(set=True, overridden=True))

    def test_docker_is_read_only(self):
        self.environ['VLOCK_SAM_EXTERNAL'] = '1'
        self.assertFalse(self.setup.view()['writable'])
        with self.assertRaises(SetupError) as caught:
            self.setup.save(dict(values=dict(META_API_KEY=KEY)))
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse(self.path.exists())

    def test_key_check_reports_model_access(self):
        self.setup.save(dict(values=dict(META_API_KEY=KEY)))
        made = []

        def factory(key, base_url):
            made.append(key)
            return Client(('muse-spark-1.3',))
        self.setup.client_factory = factory
        result = self.setup.test_meta()
        self.assertEqual((result['sam'], result['muse']), (False, True))
        self.assertNotIn(KEY, str(result))
        self.assertEqual(made, [KEY])

    def test_key_check_failures(self):
        with self.assertRaises(SetupError):
            self.setup.test_meta()
        self.setup.save(dict(values=dict(META_API_KEY=KEY)))
        rejected = APIStatusError.__new__(APIStatusError)
        rejected.status_code = 401
        offline = APIConnectionError.__new__(APIConnectionError)
        for error, text in ((rejected, 'rejected'), (offline, 'Cannot reach')):
            self.setup.client_factory = lambda key, url, failure=error: Client(error=failure)
            with self.subTest(text), self.assertRaises(SetupError) as caught:
                self.setup.test_meta()
            self.assertIn(text, str(caught.exception))
            self.assertNotIn(KEY, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
