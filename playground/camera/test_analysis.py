"""Offline checks: no real credentials, camera, or paid requests are used."""
import base64
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import analysis
import app as camera_app

# JPEG marker bytes are enough here because provider transport is mocked.
JPEG = b"\xff\xd8\xff\xe0fixture\xff\xd9"


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-only',
            'ANTHROPIC_MODEL': 'test-model',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_custom_prompt_and_exact_image(self):
        with patch.object(analysis, 'Anthropic') as sdk:
            client = sdk.return_value.__enter__.return_value
            client.messages.create.return_value = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text',text='Two pens.')])
            result = analysis.analyze_photo(JPEG, 'How many pens?')
            sent = client.messages.create.call_args.kwargs
            content = sent['messages'][0]['content']
            self.assertEqual(content[1]['text'], 'How many pens?')
            self.assertEqual(content[0]['source'], {'type':'base64', 'media_type':'image/jpeg', 'data':base64.b64encode(JPEG).decode()})
            self.assertEqual(sent['max_tokens'],1024)
            self.assertEqual(result['answer'], 'Two pens.')

    def test_blank_prompt_uses_description(self):
        with patch.object(analysis, 'Anthropic') as sdk:
            sdk.return_value.__enter__.return_value.messages.create.return_value = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text',text='A desk.')])
            result = analysis.analyze_photo(JPEG, '  ')
            self.assertEqual(result['prompt'], analysis.DEFAULT_PROMPT)

    def test_missing_key_makes_no_request(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), patch.object(analysis, 'Anthropic') as sdk:
            with self.assertRaises(analysis.AnalysisError) as raised:
                analysis.analyze_photo(JPEG, '')
            self.assertEqual(raised.exception.status, 503)
            sdk.assert_not_called()

    def test_incomplete_answer_is_not_success(self):
        with patch.object(analysis, 'Anthropic') as sdk:
            sdk.return_value.__enter__.return_value.messages.create.return_value = SimpleNamespace(stop_reason='max_tokens', content=[SimpleNamespace(type='text',text='Partial')])
            with self.assertRaises(analysis.AnalysisError):
                analysis.analyze_photo(JPEG, '')

    def test_unexpected_exception_is_sanitized(self):
        with patch.object(analysis, 'Anthropic', side_effect=RuntimeError('private-secret')):
            with self.assertRaises(analysis.AnalysisError) as raised:
                analysis.analyze_photo(JPEG, '')
            self.assertNotIn('private-secret', str(raised.exception))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = camera_app.app.test_client()
        self.capture_id = str(uuid4())

    def send(self, prompt='', photo=JPEG, origin='http://localhost:5050'):
        return self.client.post('/api/analyze', base_url='http://localhost:5050',
            headers={'Origin': origin}, data={
                'photo': (BytesIO(photo), 'capture.jpg', 'image/jpeg'),
                'prompt': prompt, 'capture_id': self.capture_id,
            })

    def test_answer_keeps_capture_identity(self):
        with patch.object(camera_app, 'analyze_photo', return_value={'answer':'A pen.', 'model':'test', 'elapsed_seconds':.1, 'prompt':'Question'}) as call:
            response = self.send('Question')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['capture_id'], self.capture_id)
            call.assert_called_once_with(JPEG, 'Question')

    def test_invalid_image_and_long_prompt_make_no_model_call(self):
        with patch.object(camera_app, 'analyze_photo') as call:
            self.assertEqual(self.send(photo=b'not-an-image').status_code, 400)
            self.assertEqual(self.send(prompt='x'*2001).status_code, 400)
            call.assert_not_called()

    def test_cross_origin_is_rejected(self):
        with patch.object(camera_app, 'analyze_photo') as call:
            self.assertEqual(self.send(origin='https://example.com').status_code, 403)
            call.assert_not_called()

    def test_safe_failure_is_displayable(self):
        with patch.object(camera_app, 'analyze_photo', side_effect=analysis.AnalysisError('Model timed out.',504)):
            response = self.send()
            self.assertEqual(response.status_code,504)
            self.assertEqual(response.json['error'],'Model timed out.')

    def test_page_and_assets(self):
        for path in ('/', '/static/app.js', '/static/style.css'):
            with self.client.get(path,base_url='http://localhost:5050') as response:
                self.assertEqual(response.status_code,200)


if __name__ == '__main__':
    unittest.main()


