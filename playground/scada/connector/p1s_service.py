"""Local Bambu P1S connector. Real hardware only; Python 3.11+.
MQTT/TLS status/control, TLS/JPEG camera, loopback HTTP for Ignition.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import socket
import ssl
import struct
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

HOME = Path(__file__).resolve().parent
LOG = logging.getLogger('bambu_p1s')
STATES = {'IDLE': 'Idle', 'READY': 'Idle', 'RUNNING': 'Running', 'PREPARE': 'Running',
          'SLICING': 'Running', 'PAUSE': 'Paused', 'FINISH': 'Completed',
          'FAILED': 'Fault', 'ERROR': 'Fault'}

class UserError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message); self.status = status


def read_env(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


class Config:
    def __init__(self, values: dict, home=HOME):
        self.home = Path(home)
        self.ip = values.get('BAMBU_IP', '192.168.1.100').strip()
        # Fixed local address only; do not accept URLs or command strings.
        try:
            address = ipaddress.ip_address(self.ip)
            if not address.is_private or address.is_loopback:
                raise ValueError()
        except ValueError:
            raise ValueError('BAMBU_IP must be the printer local IP address') from None
        self.serial = values.get('BAMBU_SERIAL', '').strip()
        self.code = values.get('BAMBU_ACCESS_CODE', '').strip()
        self.firmware = values.get('BAMBU_FIRMWARE', '')
        if self.serial and not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', self.serial):
            raise ValueError('Invalid printer serial number')
        if self.code and (not self.code.isascii() or not 1 <= len(self.code) <= 32):
            raise ValueError('Invalid LAN access code')
        self.print_file = values.get('BAMBU_PRINT_FILE', '').strip().replace('\\', '/')
        self.plate = int(values.get('BAMBU_PLATE', '1'))
        if not 1 <= self.plate <= 100:
            raise ValueError('BAMBU_PLATE must be between 1 and 100')
        self.filament_source = values.get('BAMBU_FILAMENT_SOURCE', 'unset').lower()
        if self.filament_source not in ('unset', 'external', 'ams'):
            raise ValueError('Choose external or ams for filament source')
        mapping = values.get('BAMBU_AMS_MAPPING', '').strip()
        self.ams_mapping = json.loads(mapping) if mapping else []
        if not isinstance(self.ams_mapping, list) or any(type(v) is not int or not -1 <= v <= 255 for v in self.ams_mapping):
            raise ValueError('BAMBU_AMS_MAPPING must be a JSON array of tray numbers')
        self.port = int(values.get('CONNECTOR_PORT', '8876'))
        if not 1024 <= self.port <= 65535:
            raise ValueError('Invalid connector port')
        self.stale_seconds = 30.0
        self.camera_enabled = values.get('CAMERA_ENABLED', 'true').lower() == 'true'

    @property
    def configured(self):
        return bool(self.serial and self.code)

    def job_payload(self, sequence: str) -> dict:
        if not self.print_file:
            raise UserError('Set BAMBU_PRINT_FILE in .env to a sliced .gcode.3mf file already on the printer microSD card', 422)
        parts = PurePosixPath(self.print_file)
        if (parts.is_absolute() or '..' in parts.parts or not self.print_file.lower().endswith('.gcode.3mf')
                or any(c in self.print_file for c in ['\n', '\r', '\x00', '?', '#', ':'])):
            raise UserError('Print file must be a relative microSD path ending in .gcode.3mf', 422)
        if self.filament_source == 'unset':
            raise UserError('Choose the actual filament source in .env: external or ams', 422)
        if self.filament_source == 'ams' and not self.ams_mapping:
            raise UserError('Set BAMBU_AMS_MAPPING to match the sliced file filament-to-tray mapping', 422)
        body = {'sequence_id': sequence, 'command': 'project_file',
                'param': 'Metadata/plate_%d.gcode' % self.plate,
                'url': 'ftp:///' + self.print_file, 'subtask_name': parts.name,
                'project_id': '0', 'profile_id': '0', 'task_id': '0', 'subtask_id': '0',
                'timelapse': False, 'bed_leveling': True, 'flow_cali': False,
                'vibration_cali': True, 'layer_inspect': False,
                'use_ams': self.filament_source == 'ams'}
        if self.filament_source == 'ams':
            body['ams_mapping'] = self.ams_mapping
        return {'print': body}


def numeric(value, low=None, high=None):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def merge_report(old: dict, delta: dict) -> dict:
    """Bambu status packets are deltas; preserve fields omitted by a packet."""
    for key, value in delta.items():
        if isinstance(value, dict) and isinstance(old.get(key), dict):
            merge_report(old[key], value)
        elif isinstance(value, list) and value and all(isinstance(x, dict) and 'id' in x for x in value):
            previous = old.get(key, [])
            indexed = {str(x['id']): copy.deepcopy(x) for x in previous if isinstance(x, dict) and 'id' in x} if isinstance(previous, list) else {}
            for item in value:
                dest = indexed.setdefault(str(item['id']), {})
                merge_report(dest, item)
            old[key] = list(indexed.values())
        else:
            old[key] = copy.deepcopy(value)
    return old


class Telemetry:
    def __init__(self, clock=time.monotonic):
        self.lock = threading.RLock(); self.clock = clock
        self.connected = False; self.last_report = None; self.data = {}
        self.last_error = ''; self.last_result = 'Waiting for printer connection'
        self.revision = 0

    def connection(self, connected):
        with self.lock:
            self.connected = connected
            # Never merge a new connection with stale values from the previous session.
            self.data = {}; self.last_report = None; self.revision += 1

    def update(self, report):
        with self.lock:
            # Only real status packets, not command acknowledgements, establish freshness.
            if not isinstance(report, dict) or not any(k in report for k in ('gcode_state', 'nozzle_temper', 'bed_temper', 'mc_percent', 'mc_remaining_time', 'ams')):
                return False
            merge_report(self.data, report)
            self.last_report = self.clock(); self.revision += 1
            return True

    def snapshot(self, config: Config):
        with self.lock:
            age = None if self.last_report is None else max(0, self.clock()-self.last_report)
            online = self.connected and age is not None and age <= config.stale_seconds
            d = self.data
            raw = str(d.get('gcode_state', '')).upper()
            state = STATES.get(raw, 'Unknown') if online else 'Offline'
            error_code = d.get('print_error', 0)
            try:
                text = str(error_code).replace('_', '')
                try: has_error = int(text, 0) != 0
                except ValueError: has_error = int(text, 16) != 0
            except (ValueError, TypeError):
                has_error = bool(error_code)
            if online and has_error and state not in ('Running', 'Paused'):
                state = 'Fault'
            # "remain" is available only for some AMS/RFID combinations. Never estimate it.
            filament = None
            ams = d.get('ams', {})
            if isinstance(ams, dict):
                active = str(ams.get('tray_now', ''))
                for unit in ams.get('ams', []) if isinstance(ams.get('ams'), list) else []:
                    if not isinstance(unit, dict) or not isinstance(unit.get('tray'), list):
                        continue
                    for tray in unit['tray']:
                        if not isinstance(tray, dict):
                            continue
                        try:
                            tray_id = str(int(unit['id'])*4 + int(tray['id']))
                        except (KeyError, ValueError, TypeError):
                            continue
                        if active == tray_id:
                            filament = numeric(tray.get('remain'), 0, 100)
            remaining = numeric(d.get('mc_remaining_time'), 0)
            def reading(key, low=None, high=None):
                return numeric(d.get(key), low, high) if online else None
            return {'configured': config.configured, 'mqtt_connected': self.connected,
                    'online': online, 'state': state, 'raw_state': raw if online else '',
                    'ip': config.ip, 'firmware_configured': config.firmware,
                    'age_seconds': round(age, 1) if age is not None else None,
                    'nozzle_temp': reading('nozzle_temper', -20, 500),
                    'bed_temp': reading('bed_temper', -20, 200),
                    'progress': reading('mc_percent', 0, 100),
                    'remaining_seconds': int(remaining*60) if online and remaining is not None else None,
                    'file_name': str(d.get('gcode_file') or d.get('subtask_name') or '') if online else '',
                    'filament_remaining': filament if online else None,
                    'fault': bool(online and (state == 'Fault' or has_error)),
                    'fault_message': ('Printer error ' + str(error_code)) if online and has_error else ('Printer reported FAILED' if online and raw == 'FAILED' else ''),
                    'last_result': self.last_result, 'connection_error': self.last_error,
                    'revision': self.revision}


class PinnedTLS(ssl.SSLContext):
    """Pin each Bambu self-signed endpoint certificate on first local connection."""
    def __new__(cls, pin_file):
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, pin_file):
        self.check_hostname = False; self.verify_mode = ssl.CERT_NONE
        self.minimum_version = ssl.TLSVersion.TLSv1_2
        self.pin_file = Path(pin_file); self.pin_lock = threading.Lock()

    def wrap_socket(self, *args, **kwargs):
        # Paho normally handshakes after wrap_socket; finish now to check the pin first.
        kwargs['do_handshake_on_connect'] = True
        stream = super().wrap_socket(*args, **kwargs)
        fingerprint = hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest()
        with self.pin_lock:
            if self.pin_file.exists():
                expected = self.pin_file.read_text().strip()
                if expected != fingerprint:
                    stream.close()
                    raise ssl.SSLError('Printer certificate changed; verify the printer before replacing its saved certificate pin')
            else:
                self.pin_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with self.pin_file.open('x') as f:
                        f.write(fingerprint + '\n')
                except FileExistsError:
                    if self.pin_file.read_text().strip() != fingerprint:
                        stream.close(); raise ssl.SSLError('Printer certificate pin mismatch')
                LOG.info('Pinned printer certificate for %s', self.pin_file.stem)
        return stream


def recv_exact(stream, size, stop=None):
    chunks = bytearray()
    while len(chunks) < size:
        if stop and stop.is_set():
            raise OSError('Stopping')
        block = stream.recv(size-len(chunks))
        if not block:
            raise EOFError('Camera connection closed')
        chunks.extend(block)
    return bytes(chunks)


def camera_auth(code: str):
    return struct.pack('<IIII32s32s', 0x40, 0x3000, 0, 0, b'bblp', code.encode('ascii'))


class Camera:
    def __init__(self, config, stop, clock=time.monotonic):
        self.config=config; self.stop=stop; self.clock=clock; self.lock=threading.RLock()
        self.frame=None; self.when=None; self.sequence=0; self.error='Camera not connected'
        self.stream=None; self.reconnect=threading.Event()

    def latest(self):
        with self.lock:
            fresh = self.frame is not None and self.when is not None and self.clock()-self.when < 10
            return (self.frame, self.sequence) if fresh else (None, self.sequence)

    def clear(self):
        with self.lock:
            self.frame=None; self.when=None; self.reconnect.set()
            if self.stream:
                try:self.stream.close()
                except OSError:pass

    def run(self):
        c=self.config
        context=PinnedTLS(c.home/'state'/'camera.sha256')
        while not self.stop.is_set():
            try:
                self.reconnect.clear()
                with socket.create_connection((c.ip, 6000), timeout=8) as raw:
                    with context.wrap_socket(raw, server_hostname=c.ip) as stream:
                        self.stream=stream; stream.settimeout(12); stream.sendall(camera_auth(c.code))
                        while not self.stop.is_set() and not self.reconnect.is_set():
                            header=recv_exact(stream,16,self.stop)
                            size=struct.unpack('<I',header[:4])[0]
                            if not 4 <= size <= 4*1024*1024:
                                raise ValueError('Invalid camera frame size')
                            frame=recv_exact(stream,size,self.stop)
                            if not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
                                raise ValueError('Camera did not send a complete JPEG frame')
                            with self.lock:
                                self.frame=frame; self.when=self.clock(); self.sequence+=1; self.error=''
            except (OSError, EOFError, ValueError) as exc:
                with self.lock:
                    self.error=str(exc); self.frame=None; self.when=None
            finally:
                self.stream=None
            self.stop.wait(3)


class Adapter:
    def __init__(self, config, mqtt_module=None, clock=time.monotonic):
        self.config=config; self.clock=clock; self.telemetry=Telemetry(clock)
        self.stop_event=threading.Event(); self.reset_event=threading.Event()
        self.camera=Camera(config,self.stop_event,clock)
        self.mqtt_module=mqtt_module; self.client=None
        self.pending={}; self.pending_lock=threading.RLock(); self.command_lock=threading.Lock()
        self.jobs_lock=threading.RLock(); self.jobs=OrderedDict(); self.threads=[]
        self.sequence=int(time.time()) % 1999999999; self.sequence_lock=threading.Lock()

    def next_sequence(self):
        with self.sequence_lock:
            self.sequence=(self.sequence % 1999999999)+1; return str(self.sequence)

    def on_connect(self, client, userdata, flags, reason, properties=None):
        ok=int(getattr(reason,'value',reason))==0
        self.telemetry.connection(ok)
        with self.telemetry.lock:
            self.telemetry.last_error='' if ok else 'MQTT login rejected; check LAN access code and Developer Mode'
        if ok:
            client.subscribe('device/'+self.config.serial+'/report',qos=0)
            self.pushall()

    def on_disconnect(self, client, userdata, flags, reason, properties=None):
        self.telemetry.connection(False)
        with self.telemetry.lock:self.telemetry.last_error='Printer disconnected; reconnecting'
        self.camera.clear()

    def on_message(self, client, userdata, message):
        try:
            packet=json.loads(message.payload.decode('utf-8'))
            if not isinstance(packet,dict):return
            body=packet.get('print',{})
            if not isinstance(body,dict):return
            self.telemetry.update(body)
            sequence=str(body.get('sequence_id',''))
            with self.pending_lock:
                waiter=self.pending.get(sequence)
                if waiter and body.get('command')==waiter['command'] and 'result' in body:
                    waiter['reply']=body; waiter['event'].set()
        except (ValueError,TypeError,UnicodeError):
            LOG.warning('Ignored invalid printer status packet')

    def pushall(self):
        if self.client:
            self.client.publish('device/'+self.config.serial+'/request',json.dumps({'pushing':{'sequence_id':self.next_sequence(),'command':'pushall'}}),qos=0)

    def _make_client(self):
        mqtt=self.mqtt_module
        if mqtt is None:
            import paho.mqtt.client as mqtt
            self.mqtt_module=mqtt
        client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='ignition-p1s-'+uuid.uuid4().hex[:12],protocol=mqtt.MQTTv311)
        client.username_pw_set('bblp',self.config.code)
        client.tls_set_context(PinnedTLS(self.config.home/'state'/'mqtt.sha256'))
        client.on_connect=self.on_connect;client.on_disconnect=self.on_disconnect;client.on_message=self.on_message
        def connect_failed(*unused):
            with self.telemetry.lock:self.telemetry.last_error='Cannot reach printer; check IP, LAN access code, Developer Mode, and certificate pins'
        client.on_connect_fail=connect_failed
        client.reconnect_delay_set(1,15)
        return client

    def _mqtt_worker(self):
        while not self.stop_event.is_set():
            client=None
            try:
                client=self._make_client(); self.client=client
                client.connect_async(self.config.ip,8883,keepalive=20)
                client.loop_start()
                while not self.stop_event.wait(5):
                    if self.reset_event.is_set():break
                    if self.telemetry.connected:self.pushall()
            except Exception:
                with self.telemetry.lock:self.telemetry.last_error='Connection failed; check IP, LAN code, firmware settings, and certificate pins'
                LOG.error('MQTT connection setup failed; check local configuration')
            finally:
                self.reset_event.clear()
                if client:
                    try:client.disconnect();client.loop_stop()
                    except Exception:pass
                self.client=None;self.telemetry.connection(False)
            self.stop_event.wait(1)

    def start(self):
        if not self.config.configured:
            with self.telemetry.lock:self.telemetry.last_error='Enter BAMBU_SERIAL and BAMBU_ACCESS_CODE in .env, then restart the connector'
            return
        for target in [self._mqtt_worker]+([self.camera.run] if self.config.camera_enabled else []):
            thread=threading.Thread(target=target,daemon=True);thread.start();self.threads.append(thread)

    def close(self):
        self.stop_event.set();self.camera.clear();self.reset_event.set()
        for thread in self.threads:thread.join(timeout=4)

    def status(self):
        result=self.telemetry.snapshot(self.config)
        frame, seq=self.camera.latest()
        result.update(camera_available=frame is not None,camera_sequence=seq,
                      camera_error=self.camera.error if self.config.camera_enabled else 'Camera disabled',
                      service='Running', print_file_configured=bool(self.config.print_file))
        return result

    def reset(self):
        self.telemetry.connection(False);self.camera.clear();self.reset_event.set()
        with self.telemetry.lock:
            self.telemetry.last_error='';self.telemetry.last_result='Reconnecting; printer faults are not cleared by software Reset'
        return {'result':'Reconnecting', 'accepted':True}

    def execute(self, action, request_id):
        if action not in ('Start', 'Pause', 'Stop', 'Reset', 'Resume'):
            raise UserError('Unknown command', 400)
        if not re.fullmatch('[A-Za-z0-9_-]{8,100}', request_id):
            raise UserError('A unique command id is required', 400)
        with self.jobs_lock:
            if request_id in self.jobs:
                job = self.jobs[request_id]
                if job['action'] != action:
                    raise UserError('Command id already used for another action', 409)
                if not job['done']:
                    raise UserError('Command is still pending; do not resend under another id', 409)
                if job['error']:
                    raise UserError(job['error'], job['status'])
                return job['response']
            self.jobs[request_id] = {'action': action, 'done': False, 'error': None}
            while len(self.jobs) > 256:
                key = next((k for k, v in self.jobs.items() if v['done']), None)
                if key is None:
                    self.jobs.pop(request_id, None)
                    raise UserError('Too many pending commands', 429)
                self.jobs.pop(key)
        locked = False
        try:
            if action != 'Stop':
                locked = self.command_lock.acquire(blocking=False)
                if not locked:
                    raise UserError('Another command is pending; Stop remains available', 409)
            response = self._execute(action)
            with self.jobs_lock:
                self.jobs[request_id].update(done=True, response=response, error=None, status=200)
            return response
        except UserError as exc:
            with self.jobs_lock:
                self.jobs[request_id].update(done=True, error=str(exc), status=exc.status)
            with self.telemetry.lock:
                self.telemetry.last_result = str(exc)
            raise
        except Exception:
            message = 'Command failed; check printer connection. Outcome is unknown; check actual state before retrying.'
            with self.jobs_lock:
                self.jobs[request_id].update(done=True, error=message, status=502)
            with self.telemetry.lock:
                self.telemetry.last_result = message
            raise UserError(message, 502) from None
        finally:
            if locked:
                self.command_lock.release()

    def _execute(self, action):
        if action == 'Reset':
            return self.reset()
        s = self.status()
        if action == 'Resume' and s['state'] != 'Paused':
            raise UserError('Resume requires a paused print')
        if not s['online'] or not self.client:
            raise UserError('Printer offline or telemetry stale; no command sent', 503)
        if action == 'Start' and s['state'] == 'Running':
            return {'accepted': True, 'result': 'Already running; no command sent'}
        if action == 'Stop' and s['state'] in ('Idle', 'Completed'):
            return {'accepted': True, 'result': 'No active print to stop'}
        if action == 'Pause' and s['state'] != 'Running':
            raise UserError('Pause requires a running print')
        if action == 'Start' and (s['fault'] or s['state'] not in ('Idle', 'Completed', 'Paused')):
            raise UserError('Printer is not ready; resolve its reported fault/state first')
        sequence = self.next_sequence()
        if action == 'Start' and s['state'] != 'Paused':
            payload = self.config.job_payload(sequence)
            command = 'project_file'
            expected = ('Running',)
        else:
            command = {'Start': 'resume', 'Pause': 'pause', 'Stop': 'stop', 'Resume': 'resume'}[action]
            payload = {'print': {'sequence_id': sequence, 'command': command, 'param': ''}}
            expected = {'Start': ('Running',), 'Pause': ('Paused',), 'Stop': ('Idle', 'Completed'), 'Resume': ('Running',)}[action]
        waiter = {'command': command, 'event': threading.Event(), 'reply': None}
        with self.pending_lock:
            self.pending[sequence] = waiter
        try:
            info = self.client.publish('device/' + self.config.serial + '/request', json.dumps(payload), qos=0, retain=False)
            if info.rc != 0:
                raise UserError('MQTT publish failed; command was not queued', 503)
            deadline = self.clock() + 12
            revision = s['revision']
            while self.clock() < deadline and (not self.stop_event.is_set()):
                reply = waiter['reply']
                if reply:
                    if str(reply.get('result', '')).upper() not in ('SUCCESS', 'OK'):
                        detail = str(reply.get('reason') or reply.get('error_code') or 'Printer rejected the command')[:200]
                        raise UserError('Printer rejected ' + action + ': ' + detail + '; check Developer Mode if authorization failed', 409)
                    result = action + ' accepted by printer; actual state is reported separately'
                    break
                current = self.status()
                if current['online'] and current['revision'] > revision and (current['state'] in expected):
                    result = action + ' confirmed by live printer state: ' + current['state']
                    break
                waiter['event'].wait(0.1)
            else:
                raise UserError('No printer acknowledgement received; outcome unknown. Check actual state before retrying.', 504)
            with self.telemetry.lock:
                self.telemetry.last_result = result
            return {'accepted': True, 'result': result}
        finally:
            with self.pending_lock:
                self.pending.pop(sequence, None)


class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self, adapter, port=None):
        self.adapter=adapter
        super().__init__(('127.0.0.1',adapter.config.port if port is None else port),Handler)

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def _allowed(self):
        # Only Gateway-side requests. Browser cross-origin requests are rejected.
        host=self.headers.get('Host','').split(':')[0].lower()
        return self.client_address[0]=='127.0.0.1' and host in ('localhost','127.0.0.1') and not self.headers.get('Origin')
    def _send(self,status,data,ctype='application/json'):
        raw=json.dumps(data,allow_nan=False).encode() if ctype=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if not self._allowed():return self._send(403,{'error':'Local Gateway requests only'})
        path=urlsplit(self.path).path
        if path=='/status':return self._send(200,self.server.adapter.status())
        if path=='/health':return self._send(200,{'service':'Running','configured':self.server.adapter.config.configured})
        if path=='/camera.jpg':
            frame,seq=self.server.adapter.camera.latest()
            if frame is None:return self._send(503,{'error':'No fresh camera frame'})
            return self._send(200,frame,'image/jpeg')
        return self._send(404,{'error':'Not found'})
    def do_POST(self):
        if not self._allowed():return self._send(403,{'error':'Local Gateway requests only'})
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':return self._send(415,{'error':'application/json required'})
        if urlsplit(self.path).path!='/command':return self._send(404,{'error':'Not found'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 1<=size<=4096:raise UserError('Invalid request size',400)
            self.connection.settimeout(5)
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict):raise UserError('Expected JSON object',400)
            response=self.server.adapter.execute(str(body.get('action','')),str(body.get('id','')))
            self._send(200,response)
        except UserError as exc:self._send(exc.status,{'error':str(exc)})
        except (ValueError,UnicodeError):self._send(400,{'error':'Invalid JSON request'})
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        except Exception:
            LOG.exception('HTTP request failed');self._send(500,{'error':'Connector error; check local logs'})
    def do_OPTIONS(self):self._send(403,{'error':'Browser access is not enabled'})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check-config',action='store_true');args=parser.parse_args()
    config=Config(read_env(HOME/'.env'))
    if args.check_config:
        print('Configuration readable. Credentials present: '+str(config.configured));return
    (HOME/'logs').mkdir(exist_ok=True)
    handler=RotatingFileHandler(HOME/'logs'/'connector.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(handler);LOG.setLevel(logging.INFO)
    adapter=Adapter(config);server=Server(adapter)
    def shutdown(*unused):
        adapter.stop_event.set();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGINT,shutdown)
    if hasattr(signal,'SIGTERM'):signal.signal(signal.SIGTERM,shutdown)
    LOG.info('Local connector started for printer %s; configured=%s',config.ip,config.configured)
    adapter.start()
    try:server.serve_forever(poll_interval=.5)
    finally:server.server_close();adapter.close()

if __name__=='__main__':main()
