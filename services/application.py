"""Server-owned workspace and camera lifecycle for the working application."""
import copy
import json
import math
import os
import re
import threading
import base64
from pathlib import Path
from uuid import uuid4

from services.vision.camera import Camera, address, fetch_jpeg
from services.vision.monitoring import Monitoring
from services.vision.transport import track_video
from services.vision.configuration import validate as validate_monitor


class ApplicationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


ZONE_DEFAULTS = dict(name='New zone', cameraName='Camera', cameraAddress='', cameraType='Pi / HTTP',
    target='person', program='', output='zone_condition', outputType='condition', persistence=.5,
    validity=10, minConfidence=0, unknownPolicy='Keep Unknown + publish reason', recheck='None',
    allowRemote=False, zone=[], areaSelected=False, extraConditions=[], ruleJoin='ALL (AND)',
    firstRelation='overlaps area')

INTEGRATION_DEFAULTS = dict(opcEnabled=False,opcMode='server',opcHost='127.0.0.1',opcPort=4845,
    opcEndpoint='opc.tcp://127.0.0.1:62541',security='Basic256Sha256 / SignAndEncrypt',profile='',
    mqttEnabled=False,mqttMode='client',mqttHost='127.0.0.1',mqttPort=1883,topic='vlock/v1',
    httpEnabled=True,httpBase='http://localhost:5056/api/v1',heartbeat=5)


def label(value, name, maximum=200, empty=False):
    if not isinstance(value,str) or len(value)>maximum or '\x00' in value or (not empty and not value.strip()):
        raise ApplicationError(f'Check {name}.')
    return value.strip()


def number(value, low, high, name):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise ApplicationError(f'{name} must be from {low} to {high}.')
    return value


def zone_config(data, zone_id):
    if not isinstance(data,dict):
        raise ApplicationError('Expected a zone configuration.')
    result = copy.deepcopy(ZONE_DEFAULTS)
    for key, default in ZONE_DEFAULTS.items():
        value = data.get(key,default)
        if isinstance(default,str):
            result[key] = label(value,key,2000 if key=='program' else 300,empty=key in ('program','cameraAddress'))
        elif isinstance(default,bool):
            if type(value) is not bool:
                raise ApplicationError(f'{key} must be true or false.')
            result[key] = value
    for key, low, high in [('persistence',0,60),('validity',1,3600),('minConfidence',0,100)]:
        result[key] = number(data.get(key,result[key]),low,high,key)
    if result['cameraAddress']:
        address(result['cameraAddress'])
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',result['output']):
        raise ApplicationError('Output name: use 1–64 letters, digits and underscores, starting with a letter.')
    points = data.get('zone',[])
    if not isinstance(points,list) or len(points)>32:
        raise ApplicationError('Use at most 32 polygon vertices.')
    result['zone'] = [[number(v,0,1,'Zone coordinate') for v in point] for point in points
                      if isinstance(point,list) and len(point)==2]
    if len(result['zone']) != len(points) or (result['areaSelected'] and len(points)<3):
        raise ApplicationError('A selected area needs at least three valid vertices.')
    extra = data.get('extraConditions',[])
    if not isinstance(extra,list) or len(extra)>5:
        raise ApplicationError('Use at most six draft conditions.')
    result['extraConditions'] = [dict(object=label(c.get('object'),'condition object'),
        relation=label(c.get('relation'),'condition relation')) for c in extra if isinstance(c,dict)]
    if len(result['extraConditions']) != len(extra):
        raise ApplicationError('Check the additional conditions.')
    result['id'] = zone_id
    size=data.get('frameSize')
    if size is not None and (not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 1<=v<=4096 for v in size)):
        raise ApplicationError('Invalid camera frame dimensions.')
    result['frameSize']=size
    return result


class Workspace:
    def __init__(self, directory, fetch=fetch_jpeg, infer=track_video):
        self.directory = Path(directory)
        self.path = self.directory/'workspace.json'
        self.lock = threading.RLock()
        self.fetch = fetch
        self.infer = infer
        self.cameras = {}
        self.monitors = {}
        self.ready = set()
        self.config = dict(name='My workspace', zones=[], integration=copy.deepcopy(INTEGRATION_DEFAULTS), eventLimit=100,
                           deployment='Separate network host', revision=0)
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                self.config = self.validate(saved)
            except (ValueError,TypeError,KeyError,OSError):
                raise ApplicationError('Saved workspace is invalid; it was not overwritten.',503) from None

    def validate(self, data):
        if not isinstance(data,dict) or not isinstance(data.get('zones'),list) or len(data['zones'])>32:
            raise ApplicationError('Use a workspace with at most 32 zones.')
        zones = []
        for zone in data['zones']:
            if not isinstance(zone,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',str(zone.get('id',''))):
                raise ApplicationError('Invalid zone identity.')
            zones.append(zone_config(zone,zone['id']))
        if len({z['id'] for z in zones})!=len(zones):
            raise ApplicationError('Zone identities must be unique.')
        limit = data.get('eventLimit',100)
        if str(limit) not in ('5','20','50','100','500'):
            raise ApplicationError('Select a supported event limit.')
        # Integration values are draft profiles until the output checkpoint.
        integration = data.get('integration',{})
        allowed = {'opcEnabled','opcMode','opcHost','opcPort','opcEndpoint','security','profile',
                   'mqttEnabled','mqttMode','mqttHost','mqttPort','topic','httpEnabled','httpBase','heartbeat'}
        if not isinstance(integration,dict) or set(integration)-allowed:
            raise ApplicationError('Check shared integration settings.')
        if any(not isinstance(v,(str,int,float,bool)) or isinstance(v,str) and len(v)>300 or
               isinstance(v,float) and not math.isfinite(v) for v in integration.values()):
            raise ApplicationError('Invalid integration value.')
        return dict(name=label(data.get('name','My workspace'),'workspace name',80),zones=zones,
            integration=copy.deepcopy(INTEGRATION_DEFAULTS)|copy.deepcopy(integration),eventLimit=int(limit),
            deployment=label(data.get('deployment','Separate network host'),'deployment'),
            revision=int(number(data.get('revision',0),0,2**53-1,'revision')))

    def persist(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as file:
            json.dump(self.config,file,allow_nan=False,indent=2)
            file.flush()
            os.fsync(file.fileno())
        temp.replace(self.path)

    def find(self, zone_id):
        zone = next((z for z in self.config['zones'] if z['id']==zone_id),None)
        if zone is None:
            raise ApplicationError('Zone not found.',404)
        return zone

    def status(self):
        with self.lock:
            result = copy.deepcopy(self.config)
            for zone in result['zones']:
                camera = self.cameras.get(zone['id'])
                runtime = camera.status() if camera else dict(connected=False,frame_size=None,error=None)
                monitor=self.monitors.get(zone['id'])
                state=monitor.status() if monitor else None
                enabled=bool(state and state['running'])
                frame=state['result'] if state else None
                fresh=bool(frame and not frame['stale'] and enabled)
                valid=bool(fresh and state['state'] in ('Warning','Normal'))
                scores=[obj['score'] for obj in frame.get('objects',[]) if isinstance(obj.get('score'),(int,float))] if frame and state['state']=='Warning' else []
                record=dict(camera=runtime,enabled=enabled,busy=bool(state and state['busy']),
                    state=('Active' if state['state']=='Warning' else 'Clear') if valid else 'Unknown',
                    valid=valid,value=(state['state']=='Warning') if valid else None,
                    reason=state['reason'] if state else 'Connect and configure the zone before monitoring.',
                    quality='Good' if valid else 'Unavailable',score=max(scores)*100 if scores else None,
                    age_seconds=frame['age_seconds'] if frame else None,
                    inference_ms=frame['elapsed_seconds']*1000 if frame and isinstance(frame.get('elapsed_seconds'),(int,float)) else None,
                    output_id=frame['output_id'] if fresh else None,count=frame.get('count') if fresh else None,
                    tracking_scope='four-frame session',actual_frames=monitor.output_id if monitor else 0)
                if not enabled:
                    record.update(state='Disabled',reason='Monitoring disabled; no current observation.')
                events=[dict(state=e['state'],value=e['type'],time=e['time']) for e in reversed(state['events'])] if state else []
                zone.update(connected=runtime['connected'],configured=zone['id'] in self.ready,
                    localEnabled=enabled,remoteEnabled=False,step=3 if zone['id'] in self.ready else 2 if runtime['connected'] else 1,
                    events=events[:self.config['eventLimit']],runtime=record)
            return dict(schema_version=1,prototype=False,workspace=result,
                capabilities=dict(camera=True,monitoring=True,transports=False,machine_commands=False,
                    supported_camera='Pi / HTTP',restart='Monitoring always starts disabled.'))

    def save(self, data):
        candidate = self.validate(data)
        with self.lock:
            if any(m.busy() for m in self.monitors.values()):
                raise ApplicationError('Stop monitoring and wait for the active window before saving settings.',409)
            if candidate['revision'] != self.config['revision']:
                raise ApplicationError('Workspace changed in another request. Reload before saving.',409)
            old = {z['id']:z for z in self.config['zones']}
            for z in candidate['zones']:
                if old.get(z['id']) != z:
                    self.ready.discard(z['id'])
                if z['id'] not in old or z['cameraAddress'] != old[z['id']]['cameraAddress']:
                    self.cameras.pop(z['id'],None)
                    self.monitors.pop(z['id'],None)
                    z.update(zone=[],areaSelected=False,frameSize=None)
            for zone_id in set(self.cameras)-{z['id'] for z in candidate['zones']}:
                self.cameras.pop(zone_id,None)
                self.monitors.pop(zone_id,None)
            candidate['revision'] += 1
            before = self.config
            self.config = candidate
            try:
                self.persist()
            except OSError:
                self.config = before
                raise
            return self.status()

    def add(self, name='New zone'):
        with self.lock:
            candidate = copy.deepcopy(self.config)
            candidate['zones'].append(zone_config({'name':name},'zone-'+uuid4().hex[:12]))
            return self.save(candidate)

    def connect(self, zone_id):
        with self.lock:
            zone = self.find(zone_id)
            if any(m.busy() for m in self.monitors.values()):
                raise ApplicationError('Stop monitoring before reconnecting cameras.',409)
            if zone['cameraType']!='Pi / HTTP':
                raise ApplicationError('Only the tested Pi / HTTP camera is wired so far.')
            camera = Camera(zone['cameraAddress'],self.fetch)
            self.cameras[zone_id] = camera
        camera.snapshot()
        with self.lock:
            if zone.get('frameSize') and zone['frameSize']!=camera.size:
                zone.update(zone=[],areaSelected=False)
            zone['frameSize']=camera.size
            monitor=Monitoring(fetch=lambda config:camera.snapshot(),infer=self.infer,
                path=self.directory/'zones'/zone_id/'monitor.json',event_limit=self.config['eventLimit'])
            monitor.connect({'camera':{'name':zone['cameraName'],'url':zone['cameraAddress']}})
            self.monitors[zone_id]=monitor
            self.ready.discard(zone_id)
            self.config['revision']+=1
            self.persist()
        return self.status()

    def disconnect(self, zone_id):
        with self.lock:
            self.find(zone_id)
            monitor=self.monitors.get(zone_id)
            if monitor:
                monitor.stop()
            self.cameras.pop(zone_id,None)
            self.ready.discard(zone_id)
            return self.status()

    def snapshot(self, zone_id):
        with self.lock:
            self.find(zone_id)
            camera = self.cameras.get(zone_id)
            if camera is None:
                raise ApplicationError('Connect the camera first.',409)
        jpeg,headers=camera.snapshot()
        with self.lock:
            zone=self.find(zone_id)
            if zone.get('frameSize')!=camera.size:
                monitor=self.monitors.get(zone_id)
                if monitor:monitor.stop()
                self.ready.discard(zone_id)
                zone.update(zone=[],areaSelected=False)
                raise ApplicationError('Camera resolution changed. Reconnect and redraw the area.',409)
        return jpeg,headers

    def configure(self,zone_id):
        with self.lock:
            zone=self.find(zone_id)
            monitor=self.monitors.get(zone_id)
            camera=self.cameras.get(zone_id)
            if not monitor or not camera or not camera.status()['connected']:
                raise ApplicationError('Connect the camera first.',409)
            if not zone['areaSelected']:
                raise ApplicationError('Select a monitoring area before saving the rule.')
            if zone['extraConditions']:
                raise ApplicationError('Multiple concepts and AND/OR rules are not wired yet. Use one reviewed condition.')
            if zone['allowRemote']:
                raise ApplicationError('Remote monitoring enable is not wired yet. Disable that option.')
            if zone['recheck']!='None' or zone['unknownPolicy']!='Keep Unknown + publish reason':
                raise ApplicationError('Second-check models are not wired yet. Keep Unknown explicitly.')
            if zone['minConfidence']!=0:
                raise ApplicationError('Calibrated score filtering is not wired. Set the minimum score to zero; scores remain diagnostic.')
            relation={'overlaps area':'mask_overlaps_zone','entirely inside area':'mask_inside_zone','absent from area':'object_absent'}.get(zone['firstRelation'])
            if relation is None:
                raise ApplicationError('Choose a supported geometric condition.')
            size=camera.size
            config=dict(camera={'name':zone['cameraName'],'url':zone['cameraAddress']},sam_prompt=zone['target'],
                validity_seconds=zone['validity'],bridge={'enabled':False,'asset_id':zone_id},
                zone={'name':zone['name'],'polygon':[[p[0]*(size[0]-1),p[1]*(size[1]-1)] for p in zone['zone']],
                      'frame_size':size},rule={'condition':relation,'min_overlap_ratio':.1,
                      'persistence_seconds':zone['persistence'],'action':'event_log' if zone['outputType']=='event' else 'warning'})
            config=validate_monitor(config,monitor.config,require_zone=True)
            monitor.save(config)
            self.ready.add(zone_id)
            return self.status()

    def enable(self,zone_id,enabled):
        if type(enabled) is not bool:
            raise ApplicationError('Monitoring enable must be true or false.')
        with self.lock:
            self.find(zone_id)
            monitor=self.monitors.get(zone_id)
            if not enabled:
                if monitor:monitor.stop()
                return self.status()
            if zone_id not in self.ready or monitor is None:
                raise ApplicationError('Connect and save a supported zone rule first.',409)
            if any(m.busy() for key,m in self.monitors.items() if key!=zone_id):
                raise ApplicationError('Only one local SAM zone may run at a time in this checkpoint.',409)
            monitor.start()
            return self.status()

    def analyzed(self,zone_id):
        with self.lock:
            self.find(zone_id)
            monitor=self.monitors.get(zone_id)
            state=monitor.status() if monitor else None
            if not state or not state['running'] or not state['result'] or state['result']['stale']:
                raise ApplicationError('No fresh analyzed frame is available.',409)
            return base64.b64decode(state['result']['annotated_image'].split(',',1)[1])

    def close(self):
        for monitor in self.monitors.values():
            monitor.stop()
        for monitor in self.monitors.values():
            if monitor.thread:
                monitor.thread.join(timeout=3)
