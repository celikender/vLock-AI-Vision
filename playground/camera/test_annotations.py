from io import BytesIO
import json
import unittest
from unittest.mock import patch
from PIL import Image
from analysis import AnalysisError
from annotations import annotate_photo


def jpeg(size=(1920,1080)):
    buffer=BytesIO()
    Image.new('RGB',size,'white').save(buffer,'JPEG')
    return buffer.getvalue()


def result(boxes):
    return {'answer':json.dumps({'answer':'Found requested objects.','boxes':boxes}), 'model':'test','elapsed_seconds':0.1}


class AnnotationTests(unittest.TestCase):
    def test_prompt_and_resize(self):
        box={'label':'eye','x1':10,'y1':20,'x2':30,'y2':40}
        with patch('annotations.analyze_photo',return_value=result([box])) as provider:
            output=annotate_photo(jpeg(),'Find my eyes')
            self.assertEqual((output['coordinate_width'],output['coordinate_height']),(1008,567))
            self.assertIn('Find my eyes',provider.call_args.args[1])
            self.assertEqual(output['boxes'],[box])
            self.assertEqual(Image.open(BytesIO(provider.call_args.args[0])).size,(1008,567))

    def test_empty_detection(self):
        with patch('annotations.analyze_photo',return_value=result([])):
            self.assertEqual(annotate_photo(jpeg(),'Find cups')['boxes'],[])

    def test_invalid_boxes(self):
        for box in ({'label':'x','x1':-1,'y1':0,'x2':2,'y2':3},
                    {'label':'x','x1':False,'y1':0,'x2':2,'y2':3},
                    {'label':'x','x1':0,'y1':0,'x2':2000,'y2':3}):
            with patch('annotations.analyze_photo',return_value=result([box])):
                with self.assertRaises(AnalysisError):
                    annotate_photo(jpeg(),'Find x')

    def test_invalid_image_never_calls_provider(self):
        with patch('annotations.analyze_photo') as provider:
            with self.assertRaises(AnalysisError):
                annotate_photo(b'bad image','find x')
            provider.assert_not_called()