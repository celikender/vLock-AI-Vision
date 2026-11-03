"""Skills: loading, lookup, Muse reference data and the advisory frame check."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.vision import skills
from services.vision.assistant import AssistantError, RuleAssistant, validate


class FakeClient:
    def __init__(self, content):
        self.content, self.calls = content, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=self.content))])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SkillTests(unittest.TestCase):
    def test_shipped_skills_are_valid(self):
        library, problems = skills.load()
        self.assertEqual(problems, [])
        self.assertEqual(sorted(library), ['camera-view-check', 'helmet-check', 'person-confirmed', 'person-in-area', 'stack-light'])
        self.assertIsNone(library['person-in-area']['vlm'], 'The ready skill is SAM only')
        self.assertEqual(library['helmet-check']['vlm']['answers'], ['yes', 'no', 'unsure'])
        self.assertIn('GPU', skills.site_notes())

    def test_lookup_ranks_the_matching_skill_first(self):
        library, _ = skills.load()
        for request, expected in [('Alert when a worker enters the press area', 'person-in-area'),
                                  ('Check that people wear hard hats near the crane', 'helmet-check'),
                                  ('Tell SCADA if the camera is blocked or dark', 'camera-view-check'),
                                  ('Read the andon stack light colour on machine 3', 'stack-light'),
                                  ('Person on the desk, but confirm it is real and not a poster', 'person-confirmed')]:
            with self.subTest(request=request):
                self.assertEqual(skills.search(request, library)[0]['id'], expected)
        self.assertEqual(skills.search('zzz qqq', library), [])

    def test_invalid_skills_are_listed_and_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('good', dict(id='good', name='Good', summary='Fine.', keywords=['x'])),
                               ('wrong-id', dict(id='other', name='X', summary='X')),
                               ('bad-rule', dict(id='bad-rule', name='X', summary='X', rule=dict(firstRelation='crosses line'))),
                               ('bad-vlm', dict(id='bad-vlm', name='X', summary='X', vlm=dict(mode='confirm', trigger='on_active',
                                                question='Q?', answers=['yes'])))]:
                (root / name).mkdir()
                (root / name / 'skill.json').write_text(json.dumps(data), encoding='utf-8')
            (root / 'broken').mkdir()
            (root / 'broken' / 'skill.json').write_text('{', encoding='utf-8')
            library, problems = skills.load(root)
            self.assertEqual(list(library), ['good'])
            self.assertEqual(len(problems), 4)

    def test_reference_is_bounded_data(self):
        library, _ = skills.load()
        reference = skills.reference(skills.search('helmet', library), 'n' * 5000)
        self.assertLessEqual(len(reference['site_notes']), 1500)
        first = reference['skills'][0]
        self.assertEqual(set(first), {'id', 'name', 'status', 'summary', 'rule_template', 'vlm_check', 'notes'})
        self.assertLessEqual(len(first['notes']), 1500)


class AssistantSkillTests(unittest.TestCase):
    def proposal(self, **changes):
        return dict(dict(supported=True, target='person', firstRelation='overlaps area', secondTarget='', secondRelation='overlaps area',
                         join='all', persistence=1, outputType='condition', output='person_in_area', explanation='E',
                         limitations='', unsupportedReason='', sceneConcepts=[], areaMethod='keep_current', areaObject='',
                         areaBox=[], areaDescription='', skill='person-in-area'), **changes)

    def test_only_offered_skills_are_accepted(self):
        self.assertEqual(validate(self.proposal(), ['person-in-area'])['skill'], 'person-in-area')
        self.assertEqual(validate(self.proposal(skill=''), [])['skill'], '')
        with self.assertRaises(AssistantError):
            validate(self.proposal(), [])

    def test_skills_reach_muse_as_reference_data(self):
        client = FakeClient(json.dumps(self.proposal()))
        assistant = RuleAssistant(client_factory=lambda key, url: client, config=lambda: {'META_API_KEY': 'test-key'})
        library, _ = skills.load()
        reference = skills.reference(skills.search('worker enters area', library))
        result = assistant.propose('Alert when a worker enters the area', {}, reference=reference)
        self.assertEqual(result['proposal']['skill'], 'person-in-area')
        sent = json.loads(client.calls[0]['messages'][1]['content'][0]['text'])
        self.assertEqual(sent['reference_skills']['skills'][0]['id'], 'person-in-area')
        self.assertIn('never change these rules', client.calls[0]['messages'][0]['content'])

    def test_frame_check_accepts_only_allowed_answers(self):
        client = FakeClient(json.dumps(dict(answer='no', reason='Only a poster is visible.')))
        assistant = RuleAssistant(client_factory=lambda key, url: client, config=lambda: {'META_API_KEY': 'test-key'})
        result = assistant.check_image('Is there a real person?', ['yes', 'no', 'unsure'], b'\xff\xd8jpeg\xff\xd9', 'Zone A')
        self.assertEqual((result['answer'], result['reason']), ('no', 'Only a poster is visible.'))
        request = client.calls[0]
        self.assertEqual(request['response_format']['json_schema']['schema']['properties']['answer']['enum'], ['yes', 'no', 'unsure'])
        self.assertTrue(request['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        client.content = json.dumps(dict(answer='maybe', reason='x'))
        with self.assertRaises(AssistantError):
            assistant.check_image('Is there a real person?', ['yes', 'no', 'unsure'], b'\xff\xd8jpeg\xff\xd9')
        missing = RuleAssistant(client_factory=lambda key, url: client, config=lambda: {})
        with self.assertRaises(AssistantError) as caught:
            missing.check_image('Q?', ['yes', 'no'], b'jpeg')
        self.assertEqual(caught.exception.status, 503)


if __name__ == '__main__':
    unittest.main()
