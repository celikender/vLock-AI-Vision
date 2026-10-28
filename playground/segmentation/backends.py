"""Explicit backend selection; never silently sends a local request to cloud."""
import http.client
import json
from urllib.parse import urlencode
from cloud import cloud_ready, cloud_segment
from masks import SegmentationError


def status():
    local={'ready':False,'message':'Start the local worker.'}
    connection=http.client.HTTPConnection('127.0.0.1',5052,timeout=1)
    try:
        connection.request('GET','/health')
        response=connection.getresponse()
        if response.status==200:
            local=json.loads(response.read(10000))
    except (OSError,ValueError,http.client.HTTPException):
        pass
    finally:
        connection.close()
    return {'cloud':{'configured':cloud_ready()},'local':local}


def segment_photo(jpeg,prompt,backend):
    if backend=='cloud':
        return cloud_segment(jpeg,prompt)
    if backend!='local':
        raise SegmentationError('Select Local GPU or Cloud API.',400)
    connection=http.client.HTTPConnection('127.0.0.1',5052,timeout=300)
    try:
        connection.request('POST','/segment?'+urlencode({'prompt':prompt}),body=jpeg,headers={'Content-Type':'image/jpeg'})
        response=connection.getresponse()
        data=response.read(12*1024*1024+1)
        if len(data)>12*1024*1024:
            raise SegmentationError('Local output is too large.')
        result=json.loads(data)
        if response.status!=200:
            raise SegmentationError(result.get('error','Local segmentation failed.'),response.status)
        return result
    except (OSError,http.client.HTTPException):
        raise SegmentationError('Cannot reach local SAM or it timed out. Start the local worker; first model load may take longer.',503) from None
    except ValueError:
        raise SegmentationError('Local SAM returned an invalid response.') from None
    finally:
        connection.close()