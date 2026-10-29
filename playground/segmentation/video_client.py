"""PC transport for bounded camera-video windows to the existing local GPU worker."""
import http.client
import json
from uuid import uuid4
from masks import SegmentationError
from video_tracking import validate_prompt, WINDOW_FRAMES, MAX_JPEG_BYTES


def track_video(frames, prompt, revision):
    prompt=validate_prompt(prompt)
    if not 2<=len(frames)<=WINDOW_FRAMES:
        raise ValueError('Use a bounded camera window.')
    boundary='camera-'+uuid4().hex
    parts=[]

    def field(name, value, filename=None):
        disposition=f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition+=f'; filename="{filename}"\r\nContent-Type: image/jpeg'
        parts.extend([f'--{boundary}\r\n{disposition}\r\n\r\n'.encode(),value,b'\r\n'])

    field('prompt',prompt.encode('utf-8'))
    field('revision',str(revision).encode())
    field('frames',json.dumps([{'sequence':frame['sequence']} for frame in frames]).encode())
    for index,frame in enumerate(frames):
        if len(frame['jpeg'])>MAX_JPEG_BYTES:
            raise SegmentationError('Use camera JPEGs below 2 MB for video tracking.',400)
        field('frame',frame['jpeg'],f'{index:05d}.jpg')
    parts.append(f'--{boundary}--\r\n'.encode())
    connection=http.client.HTTPConnection('127.0.0.1',5052,timeout=300)
    try:
        connection.request('POST','/video/track',body=b''.join(parts),headers={
            'Content-Type':f'multipart/form-data; boundary={boundary}'})
        response=connection.getresponse()
        if response.status!=200:
            data=json.loads(response.read(10000))
            raise SegmentationError(data.get('error','Video request failed.'),response.status)
        seen=set()
        while True:
            line=response.readline(16*1024*1024+1)
            if not line:
                break
            if len(line)>16*1024*1024:
                raise SegmentationError('Video frame output is too large.')
            result=json.loads(line)
            if result.get('type')=='error':
                raise SegmentationError(result.get('error','Video inference failed.'))
            index=result.get('frame_index')
            if (result.get('type')!='frame' or result.get('prompt')!=prompt or
                    result.get('prompt_revision')!=revision or type(index) is not int or
                    not 0<=index<len(frames) or index in seen or
                    result.get('frame_sequence')!=frames[index]['sequence']):
                raise SegmentationError('Video response does not match this prompt/camera window.')
            seen.add(index)
            yield result
        if seen!=set(range(len(frames))):
            raise SegmentationError('Video stream ended before all frames were returned.')
    except (OSError,http.client.HTTPException):
        raise SegmentationError('Local video worker unavailable or timed out. Check port 5052.',503) from None
    except (ValueError,KeyError,TypeError):
        raise SegmentationError('Local video worker returned invalid JSON.') from None
    finally:
        connection.close()
