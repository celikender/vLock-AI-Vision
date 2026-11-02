"""Working Zones application. Existing camera and bridge experiments stay separate."""
import argparse
import json
import sys
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.application import Workspace, ApplicationError
from services.vlock.store import BridgeError

STATIC = Path(__file__).with_name('app')


def make_server(workspace, port=5056):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def reply(self,code,value,mime='application/json; charset=utf-8',headers=None):
            body = value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode()
            self.send_response(code)
            for key,val in {'Content-Type':mime,'Content-Length':str(len(body)),'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",**(headers or {})}.items():
                self.send_header(key,val)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionError,TimeoutError):
                pass

        def local(self,write=False):
            self.connection.settimeout(8)
            host = self.headers.get('Host')
            if host not in (f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'):
                raise ApplicationError('Use the local application address.',403)
            origin = self.headers.get('Origin')
            if origin is not None and origin!='http://'+host or self.headers.get('Sec-Fetch-Site')=='cross-site':
                raise ApplicationError('Cross-site application requests are not allowed.',403)
            if write and origin!='http://'+host:
                raise ApplicationError('Write requests require the local application origin.',403)

        def do_GET(self):
            try:
                self.local()
                path = urlsplit(self.path).path
                if path=='/api/app/workspace':
                    return self.reply(200,workspace.status())
                if path in ('/api/v1/assets','/api/v1/health') or path.startswith('/api/v1/assets/'):
                    snapshot=workspace.observations.snapshot()
                    if path=='/api/v1/health':
                        return self.reply(200,{key:value for key,value in snapshot.items() if key!='assets'})
                    if path=='/api/v1/assets':
                        return self.reply(200,snapshot)
                    asset_id=path.removeprefix('/api/v1/assets/')
                    asset=next((a for a in snapshot['assets'] if a['asset_id']==asset_id),None)
                    if asset is None:
                        raise ApplicationError('No observations for this asset.',404)
                    return self.reply(200,{key:value for key,value in snapshot.items() if key!='assets'}|asset)
                if path=='/api/v1/events':
                    query=parse_qs(urlsplit(self.path).query)
                    limit=int(query.get('limit',['5'])[0])
                    after=int(query['after'][0]) if 'after' in query else None
                    if not 1<=limit<=200 or after is not None and not 0<=after<=2**63-1:
                        raise ApplicationError('Use limit 1–200 and a nonnegative 64-bit after cursor.')
                    events=workspace.observations.events(after,limit)
                    history=workspace.observations.history_info()
                    return self.reply(200,dict(schema_version=1,events=events,**history,
                        cursor_expired=after is not None and history['oldest_revision'] is not None and after+1<history['oldest_revision']))
                parts=path.strip('/').split('/')
                if len(parts)==5 and parts[:3]==['api','app','zones'] and parts[4]=='snapshot':
                    jpeg,headers=workspace.snapshot(parts[3])
                    return self.reply(200,jpeg,'image/jpeg',headers)
                if len(parts)==5 and parts[:3]==['api','app','zones'] and parts[4]=='analyzed':
                    return self.reply(200,workspace.analyzed(parts[3]),'image/png')
                allowed={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/ui.js':'ui.js',
                    '/scene.js':'scene.js','/runtime.js':'runtime.js','/camera-preview.js':'camera-preview.js','/style.css':'style.css',
                    '/polish.css':'polish.css','/runtime.css':'runtime.css','/README.md':'README.md'}
                if path not in allowed:
                    raise ApplicationError('Not found.',404)
                file=STATIC/allowed[path]
                mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.md':'text/plain'}[file.suffix]+'; charset=utf-8'
                return self.reply(200,file.read_bytes(),mime)
            except (ApplicationError,BridgeError) as error:
                self.reply(error.status,dict(error=str(error)))
            except ValueError:
                self.reply(400,dict(error='Check the application request.'))
            except (OSError,sqlite3.Error):
                self.reply(503,dict(error='Camera or application storage unavailable. No result was confirmed.'))

        def do_POST(self):
            try:
                self.local(write=True)
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':
                    raise ApplicationError('Send JSON with Content-Length.')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256*1024:
                    raise ApplicationError('Request is empty or too large.',413)
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):
                    raise ApplicationError('Expected a JSON object.')
                if self.path=='/api/app/workspace':
                    return self.reply(200,workspace.save(data))
                if self.path=='/api/app/zones':
                    return self.reply(201,workspace.add(data.get('name','New zone')))
                parts=self.path.strip('/').split('/')
                if len(parts)==5 and parts[:3]==['api','app','zones']:
                    if parts[4]=='connect':
                        return self.reply(200,workspace.connect(parts[3]))
                    if parts[4]=='disconnect':
                        return self.reply(200,workspace.disconnect(parts[3]))
                    if parts[4]=='configure':
                        return self.reply(200,workspace.configure(parts[3]))
                    if parts[4]=='enable':
                        return self.reply(200,workspace.enable(parts[3],data.get('enabled')))
                raise ApplicationError('This function is not wired yet.',404)
            except ApplicationError as error:
                self.reply(error.status,dict(error=str(error)))
            except (ValueError,TypeError,KeyError,RecursionError):
                self.reply(400,dict(error='Invalid request. Check the configuration fields.'))
            except (OSError,sqlite3.Error):
                self.reply(503,dict(error='Camera or storage unavailable. Check the connection before retrying.'))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def main():
    parser=argparse.ArgumentParser(description='vLock-AI Vision application')
    parser.add_argument('--port',type=int,default=5056)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'playground'/'data'/'application')
    args=parser.parse_args()
    workspace=Workspace(args.data_dir)
    server=make_server(workspace,args.port)
    print(f'vLock-AI Vision: http://localhost:{server.server_port}',flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        workspace.close()


if __name__=='__main__':
    main()
