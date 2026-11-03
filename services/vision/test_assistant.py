"""Muse rule-proposal checks with an injected client; no network or paid requests."""
import json
import threading
import unittest
from types import SimpleNamespace

from services.vision.assistant import RuleAssistant, AssistantError

KEY = 'test-only-key'
DRAFT = dict(name='A-101', target='person', firstRelation='overlaps area', persistence=.5,
             outputType='condition', output='zone_condition', areaSelected=True)
GOOD = dict(supported=True, target='person', firstRelation='overlaps area', persistence=.5,
            outputType='condition', output='person_in_cutter_area', explanation='Active when a person overlaps the area.',
            limitations='Sampled about once per second.', unsupportedReason='', sceneConcepts=[],
            areaMethod='sam_object', areaObject='glass cutter table', areaBox=[], areaDescription='Cutter table')


def reply(content, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))])


class FakeClient:
    def __init__(self, response, calls, gate=None):
        self.response, self.calls, self.gate = response, calls, gate
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.gate:
            self.gate[0].set()
            self.gate[1].wait(2)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def assistant(response, calls=None, config=None, gate=None):
    calls = [] if calls is None else calls
    settings = config if config is not None else {'META_API_KEY': KEY, 'META_MUSE_MODEL': 'muse-spark-1.3'}
    return RuleAssistant(lambda key, url: FakeClient(response, calls, gate), lambda: settings)


class AssistantTests(unittest.TestCase):
    def test_valid_proposal_uses_structured_output_and_no_frame_by_default(self):
        calls = []
        result = assistant(reply(json.dumps(GOOD)), calls).propose('Watch the cutter for people', DRAFT)
        self.assertEqual(result['proposal']['output'], 'person_in_cutter_area')
        self.assertFalse(result['frame_included'])
        request = calls[0]
        self.assertEqual(request['model'], 'muse-spark-1.3')
        self.assertEqual(request['response_format']['type'], 'json_schema')
        content = request['messages'][1]['content']
        self.assertEqual([part['type'] for part in content], ['text'])
        self.assertEqual(json.loads(content[0]['text'])['current_draft'], DRAFT)

    def test_frame_is_sent_only_when_given(self):
        calls = []
        assistant(reply(json.dumps(GOOD | {'sceneConcepts': ['person', 'saw blade']})), calls).propose(
            'Watch the cutter', DRAFT, b'\xff\xd8jpeg\xff\xd9')
        image = calls[0]['messages'][1]['content'][1]
        self.assertEqual(image['type'], 'image_url')
        self.assertTrue(image['image_url']['url'].startswith('data:image/jpeg;base64,'))

    def test_unsupported_request_is_returned_without_rule_fields(self):
        answer = dict(GOOD, supported=False, target='', unsupportedReason='Waving is a gesture.')
        proposal = assistant(reply(json.dumps(answer))).propose('Alert when someone waves', DRAFT)['proposal']
        self.assertFalse(proposal['supported'])
        self.assertNotIn('target', proposal)
        with self.assertRaises(AssistantError):
            assistant(reply(json.dumps(answer | {'unsupportedReason': ''}))).propose('Waving', DRAFT)

    def test_area_choice_is_validated(self):
        proposal = assistant(reply(json.dumps(GOOD))).propose('Watch the cutter', DRAFT)['proposal']
        self.assertEqual(proposal['area'], dict(method='sam_object', object='glass cutter table',
                                                description='Cutter table', box=None))
        box = assistant(reply(json.dumps(GOOD | dict(areaMethod='muse_box', areaObject='', areaBox=[.1, .2, .5, .9]))))
        self.assertEqual(box.propose('Left half', DRAFT)['proposal']['area']['box'], [.1, .2, .5, .9])
        for change in [dict(areaMethod='lasso'), dict(areaObject=''), dict(areaMethod='muse_box', areaBox=[]),
                       dict(areaMethod='muse_box', areaBox=[.5, .5, .1, .1]), dict(areaMethod='muse_box', areaBox=[0, 0, 2, 1]),
                       dict(areaBox='left')]:
            with self.subTest(change=change), self.assertRaises(AssistantError):
                assistant(reply(json.dumps(GOOD | change))).propose('Watch', DRAFT)

    def test_unexecutable_proposals_are_rejected_not_repaired(self):
        for change in [dict(firstRelation='crosses line'), dict(outputType='command'), dict(persistence=-1),
                       dict(persistence=float('nan')), dict(persistence='0.5'), dict(output='1bad name'),
                       dict(target=''), dict(target='x'*201), dict(supported='yes'), dict(sceneConcepts=['a']*9)]:
            with self.subTest(change=change), self.assertRaises(AssistantError):
                assistant(reply(json.dumps(GOOD | change, allow_nan=True))).propose('Watch', DRAFT)

    def test_incomplete_or_malformed_responses_fail_closed(self):
        for response in [reply(json.dumps(GOOD), finish='length'), reply('not json'), reply(None),
                         SimpleNamespace(choices=[])]:
            with self.subTest(response=response), self.assertRaises(AssistantError):
                assistant(response).propose('Watch', DRAFT)

    def test_missing_key_and_bad_text_make_no_request(self):
        calls = []
        with self.assertRaises(AssistantError) as caught:
            assistant(reply(json.dumps(GOOD)), calls, config={}).propose('Watch', DRAFT)
        self.assertEqual(caught.exception.status, 503)
        for text in ['', '   ', 'x'*2001, None]:
            with self.subTest(text=text), self.assertRaises(AssistantError):
                assistant(reply(json.dumps(GOOD)), calls).propose(text, DRAFT)
        self.assertEqual(calls, [])
        self.assertFalse(RuleAssistant(config=lambda: {}).status()['configured'])

    def test_client_errors_do_not_expose_secrets(self):
        with self.assertRaises(AssistantError) as caught:
            assistant(RuntimeError('secret '+KEY)).propose('Watch', DRAFT)
        self.assertNotIn(KEY, str(caught.exception))

    def test_one_request_at_a_time(self):
        gate = (threading.Event(), threading.Event())
        busy = assistant(reply(json.dumps(GOOD)), gate=gate)
        worker = threading.Thread(target=busy.propose, args=('Watch', DRAFT))
        worker.start()
        try:
            self.assertTrue(gate[0].wait(2))
            with self.assertRaises(AssistantError) as caught:
                busy.propose('Watch again', DRAFT)
            self.assertEqual(caught.exception.status, 409)
        finally:
            gate[1].set()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
