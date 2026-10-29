import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json
import event_prompt


class EventPromptTests(unittest.TestCase):
    def call(self, result):
        with patch.object(event_prompt, 'dotenv_values', return_value={'ANTHROPIC_API_KEY':'test'}), \
             patch.dict(event_prompt.os.environ, {}, clear=True), \
             patch.object(event_prompt, 'Anthropic') as factory:
            client = factory.return_value.__enter__.return_value
            client.messages.create.return_value = SimpleNamespace(stop_reason='end_turn',
                content=[SimpleNamespace(type='text', text=json.dumps(result))])
            output = event_prompt.interpret('When I move both hands')
            args = client.messages.create.call_args.kwargs
            self.assertIsInstance(args['messages'][0]['content'], str)
            return output

    def test_hand_rule_has_fixed_segmentation_prompt(self):
        result = self.call({'rule':'two_hands_moving','prompt':'anything','explanation':'Move hands.'})
        self.assertEqual(result['prompt'], 'hand')

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ValueError):
            self.call({'rule':'run_code','prompt':'hand','explanation':'unknown'})

    def test_unsupported_is_explicit(self):
        result = self.call({'rule':'unsupported','prompt':'','explanation':'Zone entry is not implemented.'})
        self.assertEqual(result['rule'], 'unsupported')

    def test_empty_request_rejected(self):
        with self.assertRaises(ValueError):
            event_prompt.interpret('')
