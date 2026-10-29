import json
import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from posture import StandUp, observe_posture


class StandUpTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.rule = StandUp(clock=lambda:self.now)

    def observe(self, posture):
        return self.rule.observe(posture, self.now)

    def test_starting_standing_does_not_trigger(self):
        self.observe('standing')
        self.observe('standing')
        self.assertEqual(self.rule.event_type, 'standing_observed')

    def test_confirmed_transition_triggers_once(self):
        self.observe('seated')
        self.observe('seated')
        self.assertTrue(self.rule.armed)
        self.observe('standing')
        self.assertTrue(self.observe('standing'))
        self.assertEqual(self.rule.event_type, 'person_stood_up')
        self.assertFalse(self.observe('standing'))

    def test_uncertainty_resets_baseline(self):
        self.observe('seated')
        self.observe('seated')
        self.observe('unknown')
        self.observe('standing')
        self.observe('standing')
        self.assertEqual(self.rule.event_type, 'standing_observed')

    def test_stale_resets_baseline(self):
        self.observe('seated')
        self.observe('seated')
        self.now += 31
        self.assertTrue(self.rule.expire())
        self.assertFalse(self.rule.armed)
        self.rule.observe('standing', 100)
        self.assertEqual(self.rule.state, 'unknown')

    def test_multiple_people_are_unknown(self):
        image = BytesIO()
        Image.new('RGB',(10,10)).save(image,'JPEG')
        with patch('posture.analyze_photo', return_value={'answer':json.dumps({
                'posture':'standing','single_person':False,'explanation':'Two people.'}),
                'model':'test','elapsed_seconds':1}):
            result = observe_posture(image.getvalue())
        self.assertEqual(result['posture'], 'unknown')
