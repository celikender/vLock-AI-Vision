"""Prompted text and labeled rectangles for a captured image."""
from io import BytesIO
import json
from PIL import Image, ImageOps, UnidentifiedImageError
from analysis import AnalysisError, analyze_photo

SCHEMA = {
    'type': 'object', 'properties': {
        'answer': {'type': 'string'},
        'boxes': {'type': 'array', 'items': {
            'type': 'object', 'properties': {
                'label': {'type': 'string'},
                **{key: {'type': 'integer'} for key in ('x1', 'y1', 'x2', 'y2')}
            }, 'required': ['label', 'x1', 'y1', 'x2', 'y2'], 'additionalProperties': False
        }}
    }, 'required': ['answer', 'boxes'], 'additionalProperties': False
}


def annotate_photo(jpeg, question):
    try:
        with Image.open(BytesIO(jpeg)) as original:
            if original.format != 'JPEG' or original.width * original.height > 20_000_000:
                raise AnalysisError('Use a JPEG smaller than 20 megapixels.', 400)
            image = ImageOps.exif_transpose(original).convert('RGB')
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise AnalysisError('Cannot read this photo. Capture another image.', 400) from None
    image.thumbnail((1008, 1008), Image.Resampling.LANCZOS)
    width, height = image.size
    data = BytesIO()
    image.save(data, 'JPEG', quality=92)
    prompt = (
        f'Answer the user request about this {width} by {height} pixel photo. '
        'Also locate the visible objects or parts requested by the user using labeled rectangles. '
        'For eyes, locate each eye separately. Use at most 20 boxes. '
        'Use integer absolute pixel coordinates x1,y1,x2,y2 with origin at top-left; '
        f'0 <= x1 < x2 <= {width}, 0 <= y1 < y2 <= {height}. '
        'If nothing requested is visible, or no localization is relevant, return an empty boxes list. '
        'Do not invent objects. State uncertainty in the answer. Labels should be short. '
        'Return the required JSON structure. User request: ' +
        (question.strip() or 'Describe this scene and mark its main visible objects.')
    )
    result = analyze_photo(data.getvalue(), prompt, output_schema=SCHEMA)
    try:
        output = json.loads(result['answer'])
        boxes = output['boxes']
        if not isinstance(output['answer'], str) or not isinstance(boxes, list) or len(boxes) > 20:
            raise ValueError()
        for box in boxes:
            if not isinstance(box['label'], str) or len(box['label']) > 120:
                raise ValueError()
            values = [box[key] for key in ('x1', 'y1', 'x2', 'y2')]
            if any(type(value) is not int for value in values):
                raise ValueError()
            x1, y1, x2, y2 = values
            if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
                raise ValueError()
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise AnalysisError('The model returned invalid annotations. Try another prompt or capture.') from None
    return {**result, 'prompt': question, 'answer': output['answer'], 'boxes': boxes,
            'coordinate_width': width, 'coordinate_height': height}