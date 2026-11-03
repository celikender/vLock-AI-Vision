"""SAM weights checksum: a checkpoint is loaded only when its SHA-256 is pinned."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.vision import sam_worker
from services.vision.masks import SegmentationError


class WeightsTests(unittest.TestCase):
    def setUp(self):
        sam_worker.verified.clear()
        sam_worker.weights_error = None

    def tearDown(self):
        sam_worker.verified.clear()
        sam_worker.weights_error = None

    def test_pinned_checksum_is_the_hugging_face_file(self):
        self.assertIn('0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6', sam_worker.accepted_checksums())

    def test_only_pinned_files_load_and_a_changed_file_is_checked_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'weights.pt'
            path.write_bytes(b'trusted weights')
            good = hashlib.sha256(b'trusted weights').hexdigest()
            with patch.object(sam_worker, 'accepted_checksums', return_value={good}):
                sam_worker.verify_weights(str(path))
                self.assertIsNone(sam_worker.weights_error)
                path.write_bytes(b'tampered weights!')
                with self.assertRaises(SegmentationError) as caught:
                    sam_worker.verify_weights(str(path))
                self.assertIn('do not match the pinned checksum', str(caught.exception))
                self.assertEqual(sam_worker.weights_error, str(caught.exception))
            with patch.dict('os.environ', {'SAM_CHECKPOINT_SHA256': hashlib.sha256(b'tampered weights!').hexdigest()}):
                sam_worker.verified.clear()
                sam_worker.verify_weights(str(path))
                self.assertIsNone(sam_worker.weights_error, 'An operator can pin a deliberately different checkpoint')


if __name__ == '__main__':
    unittest.main()
