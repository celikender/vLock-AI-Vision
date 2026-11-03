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
from services.vision.masks import SegmentationError
from services.vision.monitoring import Monitoring
from services.vision.transport import track_video, segment_regions
from services.vision.configuration import validate as validate_monitor
from services.vision.assistant import RuleAssistant, AssistantError
from services.vlock.store import Store as ObservationStore, BridgeError
from services.vlock.output import ObservationOutput
from services.vlock.transports import Integrations, configuration as transport_configuration
from collections import deque


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


def transport_settings(integration):
    """Map the workspace integration profile onto the existing adapter contract."""
    i=integration
    if i['opcEnabled'] and i['opcMode']!='server':
        raise ApplicationError('OPC UA client mode needs explicit node mappings. Use Host server mode in this app.')
    if i['opcEnabled'] and i['opcHost'] not in ('127.0.0.1','localhost'):
        raise ApplicationError('The OPC UA server listens on this PC only: use host 127.0.0.1.')
    if i['mqttEnabled'] and i['mqttMode']!='client':
        raise ApplicationError('Hosting an MQTT broker is not supported. Use client mode with a local broker.')
    try:
        ports=int(i['opcPort']),int(i['mqttPort'])
    except (TypeError,ValueError):
        raise ApplicationError('Ports must be whole numbers.') from None
    if any(port!=value for port,value in zip(ports,(i['opcPort'],i['mqttPort']))):
        raise ApplicationError('Ports must be whole numbers.')
    data=dict(mqtt=dict(enabled=bool(i['mqttEnabled']),host=str(i['mqttHost']) if i['mqttEnabled'] else '127.0.0.1',
                        port=ports[1],topic_prefix=str(i['topic'])),
              opcua=dict(enabled=bool(i['opcEnabled']),port=ports[0],mode='server',endpoint='opc.tcp://127.0.0.1:62541',
                         security='Basic256Sha256',reads=[],writes=[],heartbeat_node_id=''))
    try:
        return transport_configuration(data)
    except BridgeError as error:
        raise ApplicationError(str(error)) from None


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
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',result['output']):
        raise ApplicationError('Output name: use 1–64 letters, digits, underscores or hyphens, starting with a letter.')
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
    def __init__(self, directory, fetch=fetch_jpeg, infer=track_video, diagnostics=None, assistant=None,
                 worker=None, regions=segment_regions):
        self.directory = Path(directory)
        self.assistant = assistant or RuleAssistant()
        self.worker = worker
        self.regions = regions
        self.path = self.directory/'workspace.json'
        self.lock = threading.RLock()
        self.fetch = fetch
        self.infer = infer
        self.diagnostics = diagnostics
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
        self.observations=ObservationStore(self.directory/'observations.sqlite3',history_limit=1000)
        # Saved enabled adapters restart with the app; they publish observations only.
        self.integrations=Integrations(self.observations,self.directory/'transports.json')
        self.integration_error=None
        try:
            self.integrations.apply(transport_settings(self.config['integration']))
        except ApplicationError as error:
            self.integration_error=str(error)

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
                    check_ms=frame['check_seconds']*1000 if frame and isinstance(frame.get('check_seconds'),(int,float)) else None,
                    objects=len(zone['extraConditions'][:1])+1,
                    output_id=frame['output_id'] if fresh else None,count=frame.get('count') if fresh else None,
                    counts=frame.get('counts') if fresh else None,
                    tracking_scope='four-frame session',actual_frames=monitor.output_id if monitor else 0)
                record['phase']='Initializing' if enabled and frame is None and 'unavailable' not in record['reason'].lower() else 'Waiting for fresh evidence' if enabled and not valid else 'Monitoring' if enabled else 'Disabled'
                record['publication']=dict(monitor.bridge.status) if monitor else dict(state='idle',message='Configure the zone first.')
                if zone['outputType']=='count' and fresh:
                    counts=frame.get('counts') or {}
                    record.update(state='Valid',value=counts if len(counts)>1 else frame['count'],valid=True,quality='Good',
                        reason='Whole-frame detection count per object; not a zone count or cumulative visitor count.'
                        if len(counts)>1 else 'Whole-frame detection count; not a zone count or cumulative visitor count.')
                elif zone['outputType']=='event' and valid:
                    record['value']={'state':state['state']}
                if not enabled:
                    record.update(state='Disabled',reason='Monitoring disabled; no current observation.')
                events=[dict(state=e['state'],value=e['type'],time=e['time']) for e in reversed(state['events'])] if state else []
                zone.update(connected=runtime['connected'],configured=zone['id'] in self.ready,
                    localEnabled=enabled,remoteEnabled=False,step=3 if zone['id'] in self.ready else 2 if runtime['connected'] else 1,
                    events=events[:self.config['eventLimit']],runtime=record,
                    tag_path=[self.config['name'],zone['name'],zone['output']])
            return dict(schema_version=1,prototype=False,workspace=result,
                sam=self.worker.status() if self.worker else None,
                integrations=dict(self.integrations.status()['adapters'],error=self.integration_error),
                diagnostics=self.diagnostics.snapshot() if self.diagnostics else {},
                capabilities=dict(camera=True,monitoring=True,observation_api=True,transports=True,machine_commands=False,
                    supported_camera='Pi / HTTP',restart='Monitoring always starts disabled.',
                    assistant=self.assistant.status()))

    def save(self, data):
        candidate = self.validate(data)
        transports = transport_settings(candidate['integration'])
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
                    old_camera=self.cameras.pop(z['id'],None)
                    if old_camera:old_camera.stop()
                    self.monitors.pop(z['id'],None)
                    z.update(zone=[],areaSelected=False,frameSize=None)
            for zone_id in set(self.cameras)-{z['id'] for z in candidate['zones']}:
                old_camera=self.cameras.pop(zone_id,None)
                if old_camera:old_camera.stop()
                self.monitors.pop(zone_id,None)
            candidate['revision'] += 1
            before = self.config
            self.config = candidate
            try:
                self.persist()
            except OSError:
                self.config = before
                raise
            if candidate['integration']!=before['integration'] or self.integration_error:
                self.integrations.apply(transports)
                self.integration_error=None
            for monitor in self.monitors.values():
                monitor.events=deque(monitor.events,maxlen=candidate['eventLimit'])
                monitor.events_store.save(list(monitor.events))
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
            previous=self.cameras.get(zone_id)
            if previous:previous.stop()
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
            camera.start()
        return self.status()

    def disconnect(self, zone_id):
        with self.lock:
            self.find(zone_id)
            monitor=self.monitors.get(zone_id)
            if monitor:
                monitor.stop()
            camera=self.cameras.pop(zone_id,None)
            if camera:camera.stop()
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
            if len(zone['extraConditions'])>1:
                raise ApplicationError('Use at most two objects per zone.')
            if zone['ruleJoin'] not in ('ALL (AND)','ANY (OR)'):
                raise ApplicationError('Combine two objects with ALL (AND) or ANY (OR).')
            if zone['allowRemote']:
                raise ApplicationError('Remote monitoring enable is not wired yet. Disable that option.')
            if zone['recheck']!='None' or zone['unknownPolicy']!='Keep Unknown + publish reason':
                raise ApplicationError('Second-check models are not wired yet. Keep Unknown explicitly.')
            if zone['minConfidence']!=0:
                raise ApplicationError('Calibrated score filtering is not wired. Set the minimum score to zero; scores remain diagnostic.')
            relations={'overlaps area':'mask_overlaps_zone','entirely inside area':'mask_inside_zone','absent from area':'object_absent'}
            relation=relations.get(zone['firstRelation'])
            if relation is None:
                raise ApplicationError('Choose a supported geometric condition.')
            second=None
            if zone['extraConditions']:
                extra=zone['extraConditions'][0]
                if extra['relation'] not in relations or not 1<=len(extra['object'])<=200:
                    raise ApplicationError('Check the second object and its condition.')
                if extra['object'].lower()==zone['target'].strip().lower():
                    raise ApplicationError('Use two different objects.')
                second={'prompt':extra['object'],'condition':relations[extra['relation']]}
            size=camera.size
            config=dict(camera={'name':zone['cameraName'],'url':zone['cameraAddress']},sam_prompt=zone['target'],
                validity_seconds=zone['validity'],bridge={'enabled':False,'asset_id':zone_id},
                zone={'name':zone['name'],'polygon':[[p[0]*(size[0]-1),p[1]*(size[1]-1)] for p in zone['zone']],
                      'frame_size':size},rule={'condition':relation,'min_overlap_ratio':.1,
                      'persistence_seconds':zone['persistence'],'action':'event_log' if zone['outputType']=='event' else 'warning',
                      'join':'all' if zone['ruleJoin']=='ALL (AND)' else 'any'},second=second)
            config=validate_monitor(config,monitor.config,require_zone=True)
            monitor.save(config)
            monitor.bridge=ObservationOutput(self.observations,zone)
            monitor.bridge.send(config,'Unknown','Monitoring is configured but disabled.')
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
            sam=self.worker.status() if self.worker else None
            if sam and sam['state']!='ready':
                raise ApplicationError('SAM 3.1 is not ready yet. '+sam['message'],409)
            monitor.start()
            return self.status()

    def propose(self,zone_id,data):
        """Ask Muse for a complete draft (rule and area). Nothing is saved or enabled here."""
        include_frame=data.get('includeFrame',False)
        if type(include_frame) is not bool:
            raise ApplicationError('includeFrame must be true or false.')
        with self.lock:
            zone=self.find(zone_id)
            draft={key:zone[key] for key in ('name','target','firstRelation','extraConditions','ruleJoin','persistence','outputType','output','areaSelected')}
            connected=bool(self.cameras.get(zone_id) and self.cameras[zone_id].status()['connected'])
        if include_frame and not connected:
            raise ApplicationError('Connect the camera so Muse can see it, or turn off the camera view.',409)
        # The newest original JPEG stays local for SAM; it goes to Meta only when opted in.
        jpeg=self.snapshot(zone_id)[0] if connected else None
        try:
            result=self.assistant.propose(data.get('text'),draft,jpeg if include_frame else None)
        except AssistantError as error:
            raise ApplicationError(str(error),error.status) from None
        proposal=result['proposal']
        if proposal['supported']:
            proposal['area']=self.propose_area(proposal['area'],jpeg)
        return result

    def propose_area(self,area,jpeg):
        """Turn Muse's area choice into a polygon: SAM outline first, Muse box as fallback."""
        method,polygon,source,note=area['method'],None,None,''
        box=area.get('box')
        rectangle=lambda b:[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]]
        if method=='whole_frame':
            polygon,source=rectangle([.01,.01,.99,.99]),'whole_frame'
        elif method=='sam_object' and jpeg is None:
            note='Connect the camera so SAM can outline “'+area['object']+'”. Draw the area yourself.'
        elif method=='sam_object':
            try:
                regions=self.regions(jpeg,area['object'])
                if regions:
                    polygon,source=regions[0]['polygon'],'sam'
                    note=f'SAM outlined “{area["object"]}”'+(f' (largest of {len(regions)} found).' if len(regions)>1 else '.')
                else:
                    note=f'SAM found no “{area["object"]}” in the current frame.'
            except SegmentationError as error:
                note=f'SAM could not outline “{area["object"]}”: {error}'
            if polygon is None and box:
                polygon,source=rectangle(box),'muse_box'
                note+=' Using Muse’s estimated box instead.'
        elif method=='muse_box':
            polygon,source=rectangle(box),'muse_box'
            note='Muse estimated this box from the camera view. Check and adjust the corners.'
        return dict(area,polygon=polygon,source=source,note=note.strip())

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
        for camera in self.cameras.values():camera.stop()
        if self.diagnostics:self.diagnostics.close()
        self.integrations.close()
        for monitor in self.monitors.values():
            if monitor.thread:
                monitor.thread.join(timeout=3)
        self.observations.close()
