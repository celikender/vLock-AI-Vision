"""Shared single-photo preparation and mask rendering for both backends."""
import base64
from io import BytesIO
from PIL import Image, ImageOps, ImageFilter, ImageChops, UnidentifiedImageError

MAX_AREA_VERTICES = 12
MAX_OBJECTS = 32


class SegmentationError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class TooManyObjects(SegmentationError):
    def __init__(self):
        super().__init__(f'More than {MAX_OBJECTS} objects found. Use a more specific object or a smaller area.')


def outline(mask):
    """Largest outer contour of one mask as a simple polygon of at most 12 normalized vertices."""
    import cv2
    import numpy as np
    pixels=(np.asarray(mask)>0).astype('uint8')
    contours,_=cv2.findContours(pixels,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour=max(contours,key=cv2.contourArea)
    perimeter=cv2.arcLength(contour,True)
    epsilon=.01*perimeter
    polygon=cv2.approxPolyDP(contour,epsilon,True)
    while len(polygon)>MAX_AREA_VERTICES:
        epsilon*=1.4
        polygon=cv2.approxPolyDP(contour,epsilon,True)
    if len(polygon)<3:
        x,y,w,h=cv2.boundingRect(contour)
        polygon=np.array([[[x,y]],[[x+w,y]],[[x+w,y+h]],[[x,y+h]]])
    width,height=mask.size
    return [[round(float(p[0][0])/width,4),round(float(p[0][1])/height,4)] for p in polygon]


def prepare(jpeg, prompt):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 200:
        raise SegmentationError('Enter one short object phrase, such as monitor (maximum 200 characters).', 400)
    try:
        with Image.open(BytesIO(jpeg)) as source:
            if source.format != 'JPEG' or source.width * source.height > 20_000_000:
                raise ValueError()
            image = ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((1008,1008), Image.Resampling.LANCZOS)
        return image
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise SegmentationError('Use a readable JPEG below 20 megapixels.', 400) from None


def render(image, masks):
    if len(masks) > MAX_OBJECTS:
        raise TooManyObjects()
    output = image.convert('RGBA')
    colors = [(60,240,150),(255,170,40),(60,180,255),(230,90,230)]
    for index, mask in enumerate(masks):
        if mask.size != image.size:
            raise SegmentationError('Mask dimensions do not match the captured image.')
        mask = mask.convert('L').point(lambda value: 255 if value else 0)
        color = colors[index % len(colors)]
        fill = Image.new('RGBA', image.size, color + (0,))
        fill.putalpha(mask.point(lambda value: 75 if value else 0))
        output = Image.alpha_composite(output, fill)
        boundary = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(3)), mask.filter(ImageFilter.MinFilter(3)))
        edge = Image.new('RGBA', image.size, color + (0,))
        edge.putalpha(boundary)
        output = Image.alpha_composite(output, edge)
    data = BytesIO()
    output.save(data, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode('ascii')