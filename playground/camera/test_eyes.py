"""Offline eye-coordinate checks using generated images, never personal photos."""
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from PIL import Image
import eyes
from analysis import AnalysisError


def photo(width=1920, height=1080):
    data = BytesIO()
    Image.new('RGB', (width,height), 'white').save(data, format='JPEG')
    return data.getvalue()


def output(boxes):
    return {'answer': json.dumps({'answer':'Test result', 'boxes':boxes}),
            'model':'test', 'elapsed_seconds':.1, 'prompt':'test'}


class EyeTests(unittest.TestCase):
    def test_resize_and_coordinate_contract(self):
        with patch.object(eyes,'analyze_photo',return_value=output([{'x1':100,'y1':90,'x2':130,'y2':105}])) as provider:
            result = eyes.locate_eyes(photo())
            self.assertEqual((result['coordinate_width'],result['coordinate_height']),(1008,567))
            sent = Image.open(BytesIO(provider.call_args.args[0]))
            self.assertEqual(sent.size,(1008,567))
            sent.close()
            self.assertEqual(provider.call_args.kwargs['output_schema'],eyes.EYE_SCHEMA)
            self.assertEqual(result['boxes'][0]['x1'],100)

    def test_no_visible_eyes_is_valid(self):
        with patch.object(eyes,'analyze_photo',return_value=output([])):
            self.assertEqual(eyes.locate_eyes(photo(640,480))['boxes'],[])

    def test_invalid_coordinates_fail(self):
        for box in ({'x1':-1,'y1':2,'x2':20,'y2':10},
                    {'x1':10,'y1':2,'x2':1,'y2':10},
                    {'x1':True,'y1':2,'x2':20,'y2':10},
                    {'x1':1,'y1':2,'x2':900,'y2':10}):
            with self.subTest(box=box), patch.object(eyes,'analyze_photo',return_value=output([box])):
                with self.assertRaises(AnalysisError): eyes.locate_eyes(photo(640,480))

    def test_malformed_json_is_displayable_error(self):
        with patch.object(eyes,'analyze_photo',return_value={'answer':'not json'}):
            with self.assertRaises(AnalysisError): eyes.locate_eyes(photo(640,480))

    def test_invalid_image_never_calls_model(self):
        with patch.object(eyes,'analyze_photo') as provider:
            with self.assertRaises(AnalysisError): eyes.locate_eyes(b'not jpeg')
            provider.assert_not_called()


if __name__ == '__main__': unittest.main()
