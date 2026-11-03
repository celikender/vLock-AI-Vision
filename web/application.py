"""Working Zones application. Existing camera and bridge experiments stay separate."""
import argparse
import hmac
import os
import shutil
import json
import sys
import socket
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.application import Workspace, ApplicationError
from services.vlock.store import BridgeError
from services.vision.diagnostics import Diagnostics
from services.vision.worker_process import SamWorker
from services.vlock import zone_tags
from services.auth import Auth, AuthError, rank

STATIC = Path(__file__).with_name('app')
DATA = ROOT/'data'/'application'
LEGACY_DATA = ROOT/'playground'/'data'/'application'


class SingleInstance:
    """Exclusive lock on <data folder>/app.lock for the life of the process.

    A second copy using the same data folder would share the history database, MQTT
    topics and SAM worker and mark the first copy's live results Unknown.
    """
    def __init__(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.file = open(Path(folder)/'app.lock', 'a+b')
        try:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('vLock-AI Vision is already running with this data folder. '
                               'Use the open window, or close it before starting again.') from None

    def release(self):
        try:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.file.close()


class Server(ThreadingHTTPServer):
    """No shared port: Windows would otherwise let a second process bind the same port."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def migrate_data():
    """One-time copy of zones and history saved before the data folder moved."""
    if DATA.exists() or not LEGACY_DATA.is_dir():
        return
    shutil.copytree(LEGACY_DATA,DATA,ignore=shutil.ignore_patterns('*.tmp','sam_worker.log'))
    print(f'Copied saved workspace from {LEGACY_DATA} to {DATA}.',flush=True)


# Minimum role per write route; reads need a login (viewer). Anything not listed is admin-only.
POST_ROLES = {'connect': 'operator', 'disconnect': 'operator', 'enable': 'operator', 'sam/restart': 'operator',
              'configure': 'admin', 'propose': 'admin', 'workspace': 'admin', 'zones': 'admin'}
PUBLIC_PAGES = {'/login': 'login.html', '/login.js': 'login.js', '/style.css': 'style.css', '/polish.css': 'polish.css'}


def make_server(workspace, port=5056, auth=None):
    auth = auth or Auth(workspace.directory)

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

        def session(self):
            cookies=dict(part.strip().split('=',1) for part in self.headers.get('Cookie','').split(';') if '=' in part)
            return auth.session(cookies.get('vlock_session',''))

        def require(self,role,action='read'):
            current=self.session()
            if current is None:
                raise ApplicationError('Log in to use vLock-AI Vision.',401)
            if rank(current['role'])<rank(role):
                auth.audit(current,action,self.path,'refused',f'needs {role}')
                raise ApplicationError(f'Your role ({current["role"]}) cannot do this; it needs {role}.',403)
            return current

        def scada_reader(self):
            """SCADA REST: open on this PC unless VLOCK_API_TOKEN is set; the UI uses its login session."""
            token=os.environ.get('VLOCK_API_TOKEN','')
            if not token or self.session() is not None:
                return
            supplied=self.headers.get('Authorization','')
            if not hmac.compare_digest(supplied.encode(),('Bearer '+token).encode()):
                raise ApplicationError('Send Authorization: Bearer <VLOCK_API_TOKEN>.',401)

        def do_GET(self):
            try:
                self.local()
                path = urlsplit(self.path).path
                if path in PUBLIC_PAGES:
                    file=STATIC/PUBLIC_PAGES[path]
                    mime={'.html':'text/html','.js':'text/javascript','.css':'text/css'}[file.suffix]+'; charset=utf-8'
                    return self.reply(200,file.read_bytes(),mime)
                if path=='/api/app/session':
                    current=self.session()
                    return self.reply(200,dict(authenticated=current is not None,setup_needed=auth.setup_needed(),
                        user=current and current['user'],role=current and current['role']))
                if path.startswith('/api/v1/'):
                    self.scada_reader()
                elif path.startswith('/api/app/'):
                    current=self.require('admin' if path in ('/api/app/users','/api/app/audit','/api/app/opcua/clients') else 'viewer')
                elif path in ('/','/index.html'):
                    if self.session() is None:
                        return self.reply(302,b'',headers={'Location':'/login'})
                if path=='/api/app/users':
                    return self.reply(200,dict(users=auth.public_users()))
                if path=='/api/app/audit':
                    return self.reply(200,dict(entries=auth.audit_tail(200)))
                if path=='/api/app/opcua/clients':
                    return self.reply(200,workspace.integrations.clients())
                if path=='/api/app/workspace':
                    status=workspace.status()
                    status['session']=dict(user=current['user'],role=current['role'])
                    return self.reply(200,status)
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
                if path=='/api/v1/zones' or path.startswith('/api/v1/zones/'):
                    zones=workspace.observations.zones()
                    if path=='/api/v1/zones':
                        return self.reply(200,zones)
                    key=path.removeprefix('/api/v1/zones/')
                    zone=next((z for z in zones['zones'] if z['TagKey']==key),None)
                    if zone is None:
                        raise ApplicationError('No zone publishes this tag key.',404)
                    return self.reply(200,{k:v for k,v in zones.items() if k!='zones'}|zone)
                if path=='/api/app/ignition/vlock-zones.json':
                    body=json.dumps(zone_tags.ignition_export(workspace.observations.zones()['zones']),indent=2).encode()
                    return self.reply(200,body,'application/json; charset=utf-8',
                                      {'Content-Disposition':'attachment; filename="vlock-zones.json"'})
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
                allowed={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/ui.js':'ui.js','/admin.js':'admin.js',
                    '/scene.js':'scene.js','/runtime.js':'runtime.js','/camera-preview.js':'camera-preview.js','/configuration.js':'configuration.js','/configuration.css':'configuration.css','/style.css':'style.css',
                    '/polish.css':'polish.css','/runtime.css':'runtime.css','/README.md':'README.md'}
                if path not in allowed:
                    raise ApplicationError('Not found.',404)
                file=STATIC/allowed[path]
                mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.md':'text/plain'}[file.suffix]+'; charset=utf-8'
                return self.reply(200,file.read_bytes(),mime)
            except (ApplicationError,BridgeError,AuthError) as error:
                self.reply(error.status,dict(error=str(error)))
            except ValueError:
                self.reply(400,dict(error='Check the application request.'))
            except (OSError,sqlite3.Error):
                self.reply(503,dict(error='Camera or application storage unavailable. No result was confirmed.'))

        def drain(self):
            """Read an unread small body before a rejection, so the client gets the answer, not a reset."""
            try:
                length=int(self.headers.get('Content-Length','0') or 0)
                if 0<length<=256*1024 and not self.headers.get('Transfer-Encoding'):
                    self.rfile.read(length)
            except (ValueError,OSError):
                pass

        def do_POST(self):
            try:
                try:
                    self.local(write=True)
                except ApplicationError:
                    self.drain()
                    raise
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':
                    raise ApplicationError('Send JSON with Content-Length.')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256*1024:
                    raise ApplicationError('Request is empty or too large.',413)
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):
                    raise ApplicationError('Expected a JSON object.')
                if self.path=='/api/app/login':
                    token=auth.login(data.get('username'),data.get('password'),self.client_address[0])
                    return self.reply(200,dict(ok=True),headers={'Set-Cookie':
                        f'vlock_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'})
                if self.path=='/api/app/logout':
                    current=self.session()
                    if current:auth.logout(current['token'])
                    return self.reply(200,dict(ok=True),headers={'Set-Cookie':'vlock_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
                if self.path=='/api/app/setup':
                    # Only while no user exists: the first account is an admin, created on this PC.
                    if not auth.setup_needed():
                        raise ApplicationError('Setup is already done. Log in instead.',409)
                    auth.create_user(dict(user='setup',role=''),data.get('username'),data.get('password'),'admin')
                    token=auth.login(data.get('username'),data.get('password'),self.client_address[0])
                    return self.reply(200,dict(ok=True),headers={'Set-Cookie':
                        f'vlock_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'})
                parts=self.path.strip('/').split('/')
                route=parts[4] if len(parts)==5 and parts[:3]==['api','app','zones'] else self.path.removeprefix('/api/app/')
                if self.path=='/api/app/password':
                    current=self.require('viewer','user.password')
                    auth.set_password(current,current['user'],data.get('password'))
                    return self.reply(200,dict(ok=True))
                current=self.require(POST_ROLES.get(route,'admin'),route)
                result=self.route(route,parts,data,current)
                auth.audit(current,route,parts[3] if len(parts)==5 else self.path,detail=self.summary(route,data))
                return result
            except (ApplicationError,AuthError) as error:
                self.reply(error.status,dict(error=str(error)))
            except (ValueError,TypeError,KeyError,RecursionError):
                self.reply(400,dict(error='Invalid request. Check the configuration fields.'))
            except (OSError,sqlite3.Error):
                self.reply(503,dict(error='Camera or storage unavailable. Check the connection before retrying.'))
        @staticmethod
        def summary(route,data):
            """Audit detail without secrets: never passwords, tokens or camera logins."""
            if route=='enable':
                return f"enabled={data.get('enabled')}"
            if route=='propose':
                return 'request: '+str(data.get('text',''))[:200]
            if route=='workspace':
                return 'zones: '+', '.join(str(z.get('name'))[:40] for z in data.get('zones',[])[:10] if isinstance(z,dict))
            if route in ('users','users/delete','opcua/clients'):
                return ' '.join(f'{k}={data.get(k)}' for k in ('username','role','id','action') if k in data)
            return ''

        def route(self,route,parts,data,current):
            if route=='workspace':
                return self.reply(200,workspace.save(data))
            if route=='zones':
                return self.reply(201,workspace.add(data.get('name','New zone')))
            if route=='sam/restart':
                if not workspace.worker:
                    raise ApplicationError('This application was started without SAM management.',409)
                workspace.worker.restart()
                return self.reply(200,workspace.status())
            if route=='users':
                return self.reply(200,dict(users=auth.create_user(current,data.get('username'),data.get('password'),data.get('role'))))
            if route=='users/delete':
                return self.reply(200,dict(users=auth.delete_user(current,data.get('username'))))
            if route=='users/password':
                auth.set_password(current,data.get('username'),data.get('password'))
                return self.reply(200,dict(users=auth.public_users()))
            if route=='opcua/clients':
                try:
                    return self.reply(200,workspace.integrations.change_client(data.get('id'),data.get('action')))
                except BridgeError as error:
                    raise ApplicationError(str(error),error.status) from None
            if len(parts)==5 and parts[:3]==['api','app','zones']:
                if route=='connect':
                    return self.reply(200,workspace.connect(parts[3]))
                if route=='disconnect':
                    return self.reply(200,workspace.disconnect(parts[3]))
                if route=='configure':
                    return self.reply(200,workspace.configure(parts[3]))
                if route=='enable':
                    return self.reply(200,workspace.enable(parts[3],data.get('enabled')))
                if route=='propose':
                    return self.reply(200,workspace.propose(parts[3],data))
            raise ApplicationError('This function is not wired yet.',404)
    return Server(('127.0.0.1',port),Handler)


def on_console_close(callback):
    """Run cleanup when the launcher window is closed; Python skips finally blocks then."""
    if os.name!='nt':
        return None
    import ctypes
    from ctypes import wintypes
    routine=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.DWORD)(
        lambda event:(callback(),False)[1] if event in (2,5,6) else False)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(routine,True)
    return routine


def main():
    parser=argparse.ArgumentParser(description='vLock-AI Vision application')
    parser.add_argument('--port',type=int,default=5056)
    parser.add_argument('--data-dir',type=Path,default=DATA)
    parser.add_argument('--no-sam',action='store_true',help='Do not start or manage the local SAM worker.')
    parser.add_argument('--open',action='store_true',help='Open the application in the default browser.')
    args=parser.parse_args()
    try:
        instance=SingleInstance(args.data_dir)
    except RuntimeError as error:
        print(error,flush=True)
        if args.open:
            webbrowser.open(f'http://localhost:{args.port}')
        sys.exit(1)
    if args.data_dir==DATA:
        migrate_data()
    worker=None if args.no_sam else SamWorker(args.data_dir/'sam_worker.log')
    workspace=Workspace(args.data_dir,diagnostics=Diagnostics(),worker=worker)
    try:
        server=make_server(workspace,args.port)
    except OSError:
        workspace.close()
        instance.release()
        print(f'Port {args.port} is used by another program. Close it or start with --port <other port>.',flush=True)
        sys.exit(1)
    url=f'http://localhost:{server.server_port}'
    print(f'vLock-AI Vision: {url}',flush=True)
    if worker:
        close_handler=on_console_close(worker.stop)
        worker.start()
        print(f'SAM 3.1 worker: starting in Ubuntu/WSL; log at {worker.log_path}',flush=True)
    if args.open:
        webbrowser.open(url)
    print('Close this window or press Ctrl+C to stop the application and its SAM worker.',flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        workspace.close()
        if worker:
            worker.stop(wait=True)
        instance.release()


if __name__=='__main__':
    main()
