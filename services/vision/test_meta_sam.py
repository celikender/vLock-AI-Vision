"""Meta SAM backend: same rows as the local worker; every failure ends in Unknown, never Clear."""
import csv
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from openai import APIConnectionError, APIStatusError, APITimeoutError
from PIL import Image

from services.vision.masks import SegmentationError
from services.vision.meta_sam import MetaSam, meta_client, parse_objects
from services.vision.monitoring import Monitoring
from services.vision.test_monitoring import config
from services.vision.video import decode_mask

# A real sam-3.1 answer (phrase "storage drawers") for a 640x480 camera frame.
ANSWER = ("<0f>0<|box;x1=196;y1=146;x2=427;y2=314;w=640;h=480;c=0.6908212304115295|>"
          "<|mask;x=0;y=0;c=0.6908212304115295;data=169,232,!!!!#ABEpvJIgIh%&60JoXx/mXq(yQFcwx'L&DX51:Q22Qm/--Ec-"
          "TJ5_d]qE@Un3s_[u=mdTb{[sQc8QMu9GA-d8L4xY#ctI(l3*Ix(Wr``a(*dv5jS05!NEAB$1o&Wi69bXCvz`/YXgp&f_Z|>\n")
VALUES = {'META_API_KEY': 'test-key'}


def camera_jpeg():
    output = BytesIO()
    Image.new('RGB', (640, 480)).save(output, 'JPEG')
    return output.getvalue()


def bare(error_class, **attributes):
    """An SDK exception without its HTTP plumbing, which the backend does not read."""
    error = error_class.__new__(error_class)
    for name, value in attributes.items():
        setattr(error, name, value)
    return error


class FakeClient:
    def __init__(self, answer=ANSWER, error=None, status='completed'):
        self.answer, self.error, self.status = answer, error, status
        self.requests = []
        self.closed = False
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(status=self.status, output_text=self.answer)

    def close(self):
        self.closed = True


class MetaSamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name)/'latency.csv'
        self.made = []

    def backend(self, client, values=VALUES, clock=time.monotonic):
        def factory(key, base_url, timeout):
            self.made.append((key, base_url, timeout))
            return client
        return MetaSam(self.log, config=lambda: values, client_factory=factory, clock=clock)

    def rows(self, backend):
        return list(backend([dict(jpeg=camera_jpeg(), sequence='7')], 'storage drawers', 3))

    def test_parser_returns_a_full_frame_mask_and_normalized_box(self):
        objects = parse_objects(ANSWER, 640, 480)
        self.assertEqual(len(objects), 1)
        self.assertAlmostEqual(objects[0]['score'], 0.6908, places=3)
        self.assertEqual(objects[0]['bbox_xywh'], [196/640, 146/480, 232/640, 169/480])
        mask = decode_mask(objects[0]['mask'])
        self.assertEqual(mask.size, (640, 480))
        self.assertEqual(mask.histogram()[255], 34895)
        self.assertEqual(mask.getbbox()[:2], (196, 146))

    def test_row_matches_the_local_worker_contract_and_keys_are_not_logged(self):
        client = FakeClient()
        row = self.rows(self.backend(client))[0]
        self.assertEqual((row['frame_index'], row['frame_sequence'], row['prompt'], row['prompt_revision'],
                          row['width'], row['height'], row['count']), (0, '7', 'storage drawers', 3, 640, 480, 1))
        request = client.requests[0]
        self.assertEqual(request['model'], 'sam-3.1')
        self.assertEqual(request['metadata']['include_confidence'], 'true')
        self.assertTrue(request['input'][0]['content'][1]['image_url'].startswith('data:image/jpeg;base64,'))
        with self.log.open(encoding='utf-8') as handle:
            logged = list(csv.DictReader(handle))
        self.assertEqual((logged[0]['backend'], logged[0]['phrase'], logged[0]['matches'], logged[0]['status']),
                         ('meta_api', 'storage drawers', '1', 'ok'))
        self.assertNotIn('test-key', self.log.read_text(encoding='utf-8'))

    def test_empty_answer_is_a_real_zero_matches(self):
        row = self.rows(self.backend(FakeClient(answer='')))[0]
        self.assertEqual((row['count'], row['objects']), (0, []))

    def test_failures_raise_and_are_logged_never_zero_objects(self):
        cases = {'timeout': FakeClient(error=bare(APITimeoutError)),
                 'connection': FakeClient(error=bare(APIConnectionError)),
                 'http_402': FakeClient(error=bare(APIStatusError, status_code=402)),
                 'http_500': FakeClient(error=bare(APIStatusError, status_code=500)),
                 'incomplete': FakeClient(status='failed'),
                 'garbage': FakeClient(answer='not segmentation text')}
        for name, client in cases.items():
            with self.subTest(name), self.assertRaises(SegmentationError):
                self.rows(self.backend(client))
            self.assertEqual(len(client.requests), 1, 'A failed call is never retried.')
        with self.assertRaises(SegmentationError):
            parse_objects(ANSWER, 300, 200)  # Mask bounds outside the camera frame.

    def test_answer_after_the_timeout_counts_as_failed(self):
        moments = iter([0, 3.5, 3.5, 3.5])
        with self.assertRaises(SegmentationError):
            self.rows(self.backend(FakeClient(), clock=lambda: next(moments)))
        with self.log.open(encoding='utf-8') as handle:
            self.assertEqual(list(csv.DictReader(handle))[0]['status'], 'late')

    def test_timeout_setting_and_client_reuse(self):
        backend = self.backend(FakeClient())
        self.rows(backend)
        self.rows(backend)
        self.assertEqual(len(self.made), 1)
        self.assertEqual(self.made[0][2], 3.0)
        self.assertEqual(MetaSam.timeout_seconds({'VLOCK_SAM_TIMEOUT_MS': '1500'}), 1.5)
        self.assertEqual(MetaSam.timeout_seconds({'VLOCK_SAM_TIMEOUT_MS': 'soon'}), 3.0)
        real = meta_client('test-key', 'https://api.meta.ai/v1', 3.0)
        self.addCleanup(real.close)
        self.assertEqual(real.max_retries, 0)

    def test_status_needs_a_key_and_counts_requests(self):
        missing = self.backend(FakeClient(), values={})
        self.assertEqual(missing.status()['state'], 'failed')
        with self.assertRaises(SegmentationError):
            self.rows(missing)
        backend = self.backend(FakeClient())
        self.rows(backend)
        status = backend.status()
        self.assertEqual((status['state'], status['calls_last_hour']), ('ready', 1))
        self.assertNotIn('test-key', str(status))

    def test_regions_outline_the_match(self):
        regions = self.backend(FakeClient()).segment_regions(camera_jpeg(), 'storage drawers')
        self.assertEqual(len(regions), 1)
        self.assertTrue(3 <= len(regions[0]['polygon']) <= 12)


class MetaSamMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeClient()
        self.backend = MetaSam(Path(self.directory.name)/'latency.csv', config=lambda: VALUES,
                               client_factory=lambda key, base_url, timeout: self.client)
        counter = [0]

        def fetch(camera):
            counter[0] += 1
            return camera_jpeg(), {'X-Frame-Sequence': str(counter[0]), 'X-Frame-Age-Ms': '0'}
        self.monitor = Monitoring(fetch=fetch, infer=self.backend, path=Path(self.directory.name)/'configuration.json')
        value = config()
        value['camera']['frame_size'] = [640, 480]
        value['zone'].update(polygon=[[0, 0], [639, 0], [639, 479], [0, 479]], frame_size=[640, 480])
        self.monitor.connect({'camera': value['camera']})
        self.monitor.save(value)
        self.addCleanup(self.finish)

    def finish(self):
        self.monitor.stop()
        if self.monitor.thread:
            self.monitor.thread.join(3)

    def wait(self, until):
        deadline = time.monotonic()+6
        while time.monotonic() < deadline and not until():
            time.sleep(.02)
        self.assertTrue(until())

    def test_one_paced_request_per_check_and_a_real_result(self):
        self.monitor.start()
        self.wait(lambda: self.monitor.status()['result'] is not None)
        status = self.monitor.status()
        self.assertEqual(status['result']['count'], 1)
        self.assertIsNotNone(status['result']['annotated_image'])
        time.sleep(1.5)
        self.assertLessEqual(len(self.client.requests), 3, 'About one request per second.')

    def test_meta_failure_turns_a_good_result_unknown(self):
        self.monitor.start()
        # The rule confirms on two observations, one check apart with this backend.
        self.wait(lambda: self.monitor.status()['state'] != 'Unknown')
        self.assertGreaterEqual(len(self.client.requests), 2)
        self.client.error = bare(APITimeoutError)
        self.wait(lambda: self.monitor.status()['state'] == 'Unknown')
        status = self.monitor.status()
        self.assertEqual(status['reason'], MetaSam.unavailable_reason)
        self.assertIsNone(status['result'])

    def test_camera_failure_has_its_own_reason_and_recovers(self):
        working = self.monitor.fetch
        self.monitor.start()
        self.wait(lambda: self.monitor.status()['state'] != 'Unknown')

        def lost(camera):
            raise OSError('Camera disconnected.')
        self.monitor.fetch = lost
        self.wait(lambda: self.monitor.status()['state'] == 'Unknown')
        self.assertEqual(self.monitor.status()['reason'], 'Camera unavailable. Check the camera connection.')
        self.monitor.fetch = working
        self.wait(lambda: self.monitor.status()['state'] != 'Unknown')

    def test_local_backend_failure_names_local_sam(self):
        def failing(frames, prompt, revision):
            raise SegmentationError('Local video worker unavailable.', 503)
            yield
        self.monitor.infer = failing
        self.monitor.start()
        self.wait(lambda: self.monitor.status()['reason'] == 'Local SAM unavailable. Check the GPU worker.')
        self.assertEqual(self.monitor.status()['state'], 'Unknown')


if __name__ == '__main__':
    unittest.main()
