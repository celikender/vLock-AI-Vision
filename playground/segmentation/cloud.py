"""SAM 3.1 cloud experiment using the official SDK and segmentation parser."""
import base64
import os
import time
from io import BytesIO
from pathlib import Path
from dotenv import dotenv_values
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError
from meta_sam_parser import image_segmentation_format, CompletedOutcome, decode_mask_to_raster
from PIL import Image
from masks import prepare, render, SegmentationError


def settings():
    return {**dotenv_values(Path(__file__).resolve().parents[2] / '.env'), **os.environ}


def cloud_ready():
    config = settings()
    return bool(config.get('META_API_KEY') or config.get('MODEL_API_KEY'))


def cloud_segment(jpeg, prompt):
    image = prepare(jpeg, prompt)
    config = settings()
    key = config.get('META_API_KEY') or config.get('MODEL_API_KEY')
    if not key:
        raise SegmentationError('Add META_API_KEY to the project .env for Cloud API mode.', 503)
    model = config.get('META_SAM_MODEL') or 'sam-3.1'
    buffer = BytesIO(); image.save(buffer,'JPEG',quality=92)
    began = time.monotonic()
    try:
        with OpenAI(api_key=key, base_url='https://api.meta.ai/v1', timeout=120, max_retries=0) as client:
            response = client.responses.create(model=model, input=[{'role':'user','content':[
                {'type':'input_text','text':prompt.strip()},
                {'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')}
            ]}], metadata={'mask_encoding':'one_bit'})
    except APITimeoutError:
        raise SegmentationError('Meta segmentation timed out. Try again.',504) from None
    except APIConnectionError:
        raise SegmentationError('Cannot reach Meta. Check your internet connection.') from None
    except APIStatusError as error:
        messages={401:'Meta key rejected. Check .env.',403:'Your Meta account cannot access SAM. Check model access.',429:'Meta quota or rate limit reached.'}
        raise SegmentationError(messages.get(error.status_code,'Meta rejected the segmentation request. Check your model access.')) from None
    except Exception:
        raise SegmentationError('Meta segmentation request failed.') from None
    if response.status != 'completed':
        raise SegmentationError('Meta returned an incomplete segmentation.')
    masks = parse_masks(response.output_text or '', image.size)
    return {'backend':'cloud','model':model,'count':len(masks),'elapsed_seconds':round(time.monotonic()-began,2),
            'annotated_image':render(image,masks),'width':image.width,'height':image.height}


def parse_masks(text, size):
    if len(text) > 16 * 1024 * 1024:
        raise SegmentationError('Segmentation response is too large.')
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if any(d.severity == 'error' for d in result.diagnostics):
        raise SegmentationError('Meta returned malformed segmentation data.')
    records = [record for record in result.records if record.kind == 'mask']
    if text.strip() and not records:
        raise SegmentationError('Meta returned text without usable masks.')
    if len(records) > 32:
        raise SegmentationError('Too many objects. Narrow the prompt.')
    masks=[]
    for record in records:
        bounds=record.bounds
        left,top,right,bottom=[int(v) for v in (bounds.left,bounds.top,bounds.right,bounds.bottom)]
        if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
            raise SegmentationError('Mask bounds do not match the submitted image.')
        mask=record.mask
        if mask.width * mask.height > 4_000_000:
            raise SegmentationError('Mask dimensions are too large.')
        raster=decode_mask_to_raster(mask)
        patch=Image.frombytes('L',(mask.width,mask.height),raster).point(lambda value:255 if value else 0)
        patch=patch.resize((right-left,bottom-top),Image.Resampling.NEAREST)
        full=Image.new('L',size);full.paste(patch,(left,top));masks.append(full)
    return masks