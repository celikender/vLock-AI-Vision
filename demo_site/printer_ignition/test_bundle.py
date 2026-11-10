"""Deployment integrity checks; never installs or starts the connector."""
import io
import json
from pathlib import Path, PurePosixPath
import unittest
from zipfile import ZipFile

import build_bundle

HERE = Path(__file__).resolve().parent


class BundleTests(unittest.TestCase):
    def test_one_current_import_and_one_connector(self):
        with ZipFile(HERE / 'output/printer-farm.zip') as archive:
            names = archive.namelist()
            expected = {'START_HERE.md', 'printer-farm-perspective.zip', 'bambu-p1s-tags.json'}
            expected.update('connector/' + name for name in build_bundle.CONNECTOR_FILES)
            self.assertEqual(set(names), expected)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual([n for n in names if n.endswith('.zip')], ['printer-farm-perspective.zip'])
            self.assertFalse(any(PurePosixPath(n).name == '.env' or '..' in PurePosixPath(n).parts for n in names))
            self.assertIsNone(archive.testzip())
            with ZipFile(io.BytesIO(archive.read('printer-farm-perspective.zip'))) as project:
                self.assertIn('project.json', project.namelist())
                self.assertIsNone(project.testzip())
                self.assertEqual(json.loads(project.read('project.json'))['title'], 'Printer Farm Control')

    def test_shipped_sources_match_the_reviewed_files(self):
        def text(data):
            # The bundle is built on Windows (CRLF); a Linux checkout of the same files has LF.
            return data.replace(b'\r\n', b'\n')
        with ZipFile(HERE / 'output/printer-farm.zip') as archive:
            for name in build_bundle.CONNECTOR_FILES:
                self.assertEqual(text(archive.read('connector/' + name)), text((HERE / 'connector' / name).read_bytes()), name)
            self.assertEqual(archive.read('printer-farm-perspective.zip'), (HERE / 'output/printer-farm-perspective.zip').read_bytes())
            self.assertEqual(text(archive.read('bambu-p1s-tags.json')), text((HERE / 'output/bambu-p1s-tags.json').read_bytes()))


if __name__ == '__main__':
    unittest.main()
