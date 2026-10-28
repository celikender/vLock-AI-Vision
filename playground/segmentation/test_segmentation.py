import base64
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from masks import prepare, render, SegmentationError
from cloud import parse_masks, cloud_segment
from backends import segment_photo

FIXTURE='<0f>0<|box;x1=2;y1=3;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=2,2,!!!!!&T:u9`|>'


def jpeg():
    buffer=BytesIO();Image.new('RGB',(10,10),'white').save(buffer,'JPEG');return buffer.getvalue()


class SegmentationTests(unittest.TestCase):
    def test_mask_positions(self):
        masks=parse_masks(FIXTURE,(10,10))
        self.assertEqual(len(masks),1)
        self.assertEqual(masks[0].getpixel((2,3)),255)
        self.assertEqual(masks[0].getpixel((3,3)),0)
        self.assertEqual(masks[0].getpixel((3,4)),255)
        self.assertEqual(masks[0].getpixel((0,0)),0)
    def test_overlay_shape_and_background(self):
        image=Image.new('RGB',(10,10),'white')
        data=render(image,parse_masks(FIXTURE,(10,10))).split(',')[1]
        output=Image.open(BytesIO(base64.b64decode(data)))
        self.assertEqual(output.size,(10,10))
        self.assertEqual(output.getpixel((9,9)),(255,255,255,255))
        self.assertNotEqual(output.getpixel((2,3)),(255,255,255,255))
    def test_empty_result(self):
        self.assertEqual(parse_masks('',(10,10)),[])
    def test_invalid_output(self):
        for output in ('unexpected prose',FIXTURE.replace('x2=3','x2=30')):
            with self.assertRaises(SegmentationError):
                parse_masks(output,(10,10))
    def test_invalid_input(self):
        with self.assertRaises(SegmentationError):prepare(b'bad','monitor')
        with self.assertRaises(SegmentationError):prepare(jpeg(),'')
    @patch('cloud.settings',return_value={})
    @patch('cloud.OpenAI')
    def test_missing_key(self,client,settings):
        with self.assertRaises(SegmentationError):cloud_segment(jpeg(),'monitor')
        client.assert_not_called()
    @patch('cloud.settings',return_value={'META_API_KEY':'test-only'})
    @patch('cloud.OpenAI')
    def test_cloud_contract(self,client,settings):
        api=client.return_value.__enter__.return_value
        api.responses.create.return_value=SimpleNamespace(status='completed',output_text=FIXTURE)
        output=cloud_segment(jpeg(),'monitor')
        self.assertEqual(output['count'],1)
        self.assertEqual(output['backend'],'cloud')
        args=api.responses.create.call_args.kwargs
        self.assertEqual(args['model'],'sam-3.1')
        self.assertEqual(args['input'][0]['content'][0]['text'],'monitor')
    @patch('backends.cloud_segment')
    @patch('backends.http.client.HTTPConnection')
    def test_local_failure_never_uses_cloud(self,connection,cloud):
        connection.return_value.request.side_effect=OSError()
        with self.assertRaises(SegmentationError):segment_photo(jpeg(),'monitor','local')
        cloud.assert_not_called()
    def test_unknown_backend(self):
        with self.assertRaises(SegmentationError):segment_photo(jpeg(),'monitor','other')