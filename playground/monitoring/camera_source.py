"""Pi snapshot access using the existing relay, with optional server-side HTTP Basic auth."""
import base64
import http.client
from urllib.parse import urlsplit


def snapshot(camera, relay):
    address = urlsplit(camera['url'])
    target = f'{address.hostname}:{address.port}'
    if not camera['username'] and not camera['password']:
        return relay(target)
    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=2)
    try:
        credential = base64.b64encode((camera['username']+':'+camera['password']).encode()).decode('ascii')
        connection.request('GET', '/snapshot.jpg', headers={'Authorization': 'Basic '+credential, 'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type','').split(';')[0] != 'image/jpeg':
            raise OSError('Camera connection failed. Check address, service and credentials.')
        body = response.read(2*1024*1024+1)
        if len(body)>2*1024*1024 or not body.startswith(b'\xff\xd8') or not body.endswith(b'\xff\xd9'):
            raise OSError('Camera returned an invalid JPEG.')
        headers = {name:response.getheader(name,'') for name in ('X-Frame-Sequence','X-Frame-Age-Ms')}
        return body, {key:value for key,value in headers.items() if value.isdigit()}
    finally:
        connection.close()
