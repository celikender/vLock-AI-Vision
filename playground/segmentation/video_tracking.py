"""Finite camera-window sessions for the installed SAM 3.1 video request API."""
import json
import logging
import math
from itertools import groupby
from PIL import Image
from masks import SegmentationError

log = logging.getLogger('sam.video')
WINDOW_FRAMES = 4
MAX_JPEG_BYTES = 2 * 1024 * 1024


def validate_prompt(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
        raise SegmentationError('Enter an object phrase of 1–200 characters.', 400)
    return value.strip()


def plain(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu()
    return value.tolist() if hasattr(value, 'tolist') else value


def mask_image(value):
    if isinstance(value, Image.Image):
        return value.convert('L').point(lambda v: 255 if v else 0)
    if hasattr(value, 'detach'):
        value = value.detach().cpu().numpy()
    if value.ndim == 3 and value.shape[0] == 1:
        value = value[0]
    if value.ndim != 2:
        raise ValueError('Unexpected SAM mask dimensions.')
    return Image.fromarray(value.astype('uint8') * 255, 'L')


def encode_mask(mask):
    """Lossless uncompressed COCO RLE: column-major, background run first."""
    pixels = mask.transpose(Image.Transpose.TRANSPOSE).tobytes()
    counts = [len(list(run)) for _, run in groupby(pixels)]
    if pixels and pixels[0]:
        counts.insert(0, 0)
    return {'encoding': 'coco_rle', 'size': [mask.height, mask.width], 'counts': counts}


def decode_mask(encoded):
    height,width=encoded['size']
    counts=encoded['counts']
    if (encoded.get('encoding')!='coco_rle' or not 0<height*width<=2_000_000 or
            any(type(n) is not int or n<0 for n in counts) or sum(counts)!=height*width):
        raise ValueError('Invalid video mask RLE.')
    pixels=b''.join(bytes([255 if index%2 else 0])*count for index,count in enumerate(counts))
    return Image.frombytes('L',(height,width),pixels).transpose(Image.Transpose.TRANSPOSE)


def serialize_frame(response, session_id, prompt, revision, metadata):
    index = response['frame_index']
    if type(index) is not int or not 0 <= index < len(metadata):
        raise ValueError('SAM returned an unexpected frame index.')
    outputs = response['outputs']
    ids = plain(outputs['out_obj_ids'])
    masks = outputs['out_binary_masks']
    boxes = plain(outputs.get('out_boxes_xywh'))
    scores = plain(outputs.get('out_probs'))
    if len(ids) != len(masks) or (boxes is not None and len(boxes) != len(ids)) or (
            scores is not None and len(scores) != len(ids)):
        raise ValueError('SAM output object arrays disagree.')
    objects = []
    for i, object_id in enumerate(ids):
        mask = mask_image(masks[i])
        if [mask.width, mask.height] != metadata[index]['size']:
            raise ValueError('SAM mask and camera dimensions disagree.')
        box = boxes[i] if boxes is not None else None
        score = float(scores[i]) if scores is not None else None
        if score is not None and not math.isfinite(score):
            raise ValueError('SAM returned a nonfinite score.')
        if box is not None and (len(box) != 4 or not all(math.isfinite(v) for v in box)):
            raise ValueError('SAM returned an invalid bounding box.')
        objects.append({'object_id': int(object_id), 'track_id': f'{session_id}:{object_id}',
                        'bbox_xywh': box, 'score': score, 'mask': encode_mask(mask)})
    result = dict(type='frame', session_id=session_id, prompt=prompt, prompt_revision=revision,
                  frame_index=index, frame_sequence=metadata[index]['sequence'],
                  width=metadata[index]['size'][0], height=metadata[index]['size'][1],
                  box_coordinates='normalized_xywh', objects=objects, count=len(objects),
                  id_scope='session', window_frames=len(metadata))
    log.info('SAM output %s', json.dumps({**{k:v for k,v in result.items() if k != 'objects'},
        'objects': [{k:v for k,v in obj.items() if k != 'mask'} | {
            'mask_size':obj['mask']['size'], 'mask_runs':len(obj['mask']['counts'])}
                    for obj in objects]}, ensure_ascii=True))
    return result


def track_window(predictor, directory, prompt, revision, metadata):
    """One session retains temporal state for the entire finite camera window.

    Closing this generator on cancellation/disconnect also closes its SAM session.
    New windows/prompts reset identities, never the loaded predictor weights.
    """
    session_id = None
    stream = None
    try:
        start = {'type':'start_session', 'resource_path':str(directory), 'offload_video_to_cpu':True}
        session_id = predictor.handle_request(request=start)['session_id']
        add = {'type':'add_prompt', 'session_id':session_id, 'frame_index':0, 'text':prompt}
        log.info('SAM request %s', json.dumps(add, ensure_ascii=True))
        seed = predictor.handle_request(request=add)
        # Log the seed, but publish the authoritative propagated frame only once.
        serialize_frame(seed, session_id, prompt, revision, metadata)
        propagation = {'type':'propagate_in_video', 'session_id':session_id,
                       'propagation_direction':'forward', 'start_frame_index':0,
                       'max_frame_num_to_track':len(metadata)}
        log.info('SAM request %s', json.dumps(propagation))
        stream = predictor.handle_stream_request(request=propagation)
        seen = set()
        for response in stream:
            index = response['frame_index']
            if index in seen:
                raise ValueError('SAM repeated a propagated frame.')
            seen.add(index)
            yield serialize_frame(response, session_id, prompt, revision, metadata)
        if seen != set(range(len(metadata))):
            raise ValueError('SAM propagation did not return every camera-window frame.')
    finally:
        try:
            if stream is not None:
                stream.close()
        finally:
            if session_id is not None:
                predictor.handle_request(request={'type':'close_session', 'session_id':session_id})
                log.info('SAM session closed %s; predictor retained', session_id)
