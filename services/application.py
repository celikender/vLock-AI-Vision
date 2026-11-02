"""Server-owned workspace and camera lifecycle for the working application."""
import copy
import json
import math
import os
import re
import threading
from pathlib import Path
from uuid import uuid4

from services.vision.camera import Camera, address, fetch_jpeg


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
    return result


class Workspace:
    def __init__(self, directory, fetch=fetch_jpeg):
        self.directory = Path(directory)
        self.path = self.directory/'workspace.json'
        self.lock = threading.RLock()
        self.fetch = fetch
        self.cameras = {}
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
                zone.update(connected=runtime['connected'],configured=False,localEnabled=False,remoteEnabled=False,
                    step=2 if runtime['connected'] else 1,events=[],runtime=dict(camera=runtime,
                    state='Unknown',valid=False,value=None,reason='Monitoring is not wired in this checkpoint.'))
            return dict(schema_version=1,prototype=False,workspace=result,
                capabilities=dict(camera=True,monitoring=False,transports=False,machine_commands=False,
                    supported_camera='Pi / HTTP',restart='Monitoring always starts disabled.'))

    def save(self, data):
        candidate = self.validate(data)
        with self.lock:
            if candidate['revision'] != self.config['revision']:
                raise ApplicationError('Workspace changed in another request. Reload before saving.',409)
            old = {z['id']:z for z in self.config['zones']}
            for z in candidate['zones']:
                if z['id'] not in old or z['cameraAddress'] != old[z['id']]['cameraAddress']:
                    self.cameras.pop(z['id'],None)
                    z.update(zone=[],areaSelected=False)
            for zone_id in set(self.cameras)-{z['id'] for z in candidate['zones']}:
                self.cameras.pop(zone_id,None)
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
            if zone['cameraType']!='Pi / HTTP':
                raise ApplicationError('Only the tested Pi / HTTP camera is wired so far.')
            camera = Camera(zone['cameraAddress'],self.fetch)
            self.cameras[zone_id] = camera
        camera.snapshot()
        return self.status()

    def disconnect(self, zone_id):
        with self.lock:
            self.find(zone_id)
            self.cameras.pop(zone_id,None)
            return self.status()

    def snapshot(self, zone_id):
        with self.lock:
            self.find(zone_id)
            camera = self.cameras.get(zone_id)
            if camera is None:
                raise ApplicationError('Connect the camera first.',409)
        return camera.snapshot()

    def close(self):
        pass
