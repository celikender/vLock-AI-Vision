"""Offline contract checks; never connects to or commands the real printer."""
import ast
import base64
import importlib.util
import json
import math
from pathlib import Path
import re
import threading
import time
import types
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent


class Atomic:
    def __init__(self, value): self.value = value
    def compareAndSet(self, expected, value):
        if self.value != expected: return False
        self.value = value
        return True
    def set(self, value): self.value = value
    def get(self): return self.value


class Lock:
    def tryLock(self): return True
    def unlock(self): pass
    def lock(self): pass


class Namespace:
    def __init__(self, values): self.values=values
    def __getattr__(self, name): return self.values[name]


def bridge():
    tree = ast.parse((HERE / 'project/ignition/script-python/bambuP1s/code.py').read_text())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    values = {}
    def defaults(nodes, prefix=''):
        for n in nodes:
            path = prefix + n['name']
            if 'tags' in n: defaults(n['tags'], path + '/')
            else: values[path.removeprefix('BambuP1S/')] = n.get('value')
    defaults(json.loads((HERE/'output/bambu-p1s-tags.json').read_text())['tags'])
    values.update({'[default]vLock/A-101/State': 'Clear',
                   '[default]vLock/A-101/Quality': 'Good',
                   '[default]vLock/A-101/Reason': 'Zone clear',
                   '[default]vLock/Bridge/Online': True,
                   '[default]vLock/Bridge/HeartbeatCounter': 1})
    bad = set()
    now = [100.0]
    client = Mock()
    system = Mock()
    system.net.httpClient.return_value = client
    system.tag.writeBlocking.side_effect = lambda paths, vals, timeout: [values.__setitem__(p.split('BambuP1S/')[1], v) or Mock(isGood=lambda: True) for p,v in zip(paths, vals)]
    system.tag.readBlocking.side_effect = lambda paths, timeout: [types.SimpleNamespace(value=values.get(p.removeprefix('[default]BambuP1S/')), quality=types.SimpleNamespace(isGood=lambda p=p: p not in bad)) for p in paths]
    system.tag.exists.return_value = True
    system.util.jsonEncode.side_effect = json.dumps
    system.util.jsonDecode.side_effect = json.loads
    system.date.format.return_value = '12:00:00'
    namespace = dict(system=system, math=math, re=re, long=int, AtomicBoolean=Atomic, ReentrantLock=Lock,
        Base64=types.SimpleNamespace(getEncoder=lambda: types.SimpleNamespace(encodeToString=lambda b: base64.b64encode(b).decode())),
        UUID=Mock(randomUUID=lambda: 'test-request-123'))
    exec(compile(tree, '<bridge>', 'exec'), namespace)
    site_tree=ast.parse((HERE/'site_logic.py').read_text(encoding='utf-8'))
    site_tree.body=[n for n in site_tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    site=dict(system=system,bambuP1s=Namespace(namespace),long=int,ReentrantLock=Lock,
              UUID=namespace['UUID'],Clock=types.SimpleNamespace(nanoTime=lambda: now[0]*1e9))
    exec(compile(site_tree,'<site>','exec'),site)
    namespace['printerSite']=Namespace(site)
    namespace['_test_site']=site
    namespace['initialize']()
    values['Config/ServiceUrl'] = 'http://127.0.0.1:8876'
    namespace['_test_now'] = now
    namespace['_test_bad'] = bad
    return namespace, system, client, values


def ready(ns,values):
    site=ns['_test_site']
    site['tick']()
    ns['_test_now'][0]+=0.25
    values['[default]vLock/Bridge/HeartbeatCounter']+=1
    site['tick']()


class BridgeTests(unittest.TestCase):
    def test_live_temperature_and_disconnect(self):
        ns, system, client, values = bridge()
        client.get.return_value = types.SimpleNamespace(good=True, json={'online':True,'mqtt_connected':True,'state':'Idle','nozzle_temp':22.5,'bed_temp':21.0,'age_seconds':1})
        ns['tick']()
        self.assertEqual(values['Readings/NozzleTemp'],22.5)
        self.assertTrue(values['Readings/BedValid'])
        client.get.side_effect = IOError('offline')
        ns['tick']()
        self.assertFalse(values['Readings/Online'])
        self.assertFalse(values['Readings/NozzleValid'])
        self.assertEqual(values['Readings/NozzleTemp'],22.5)

    def test_no_fabricated_zero_or_nan(self):
        ns, system, client, values = bridge()
        client.get.return_value = types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'nozzle_temp':None,'bed_temp':float('nan')})
        ns['tick']()
        self.assertFalse(values['Readings/NozzleValid'])
        self.assertFalse(values['Readings/BedValid'])


    def test_request_consumption_stop_priority(self):
        ns, system, client, values = bridge()
        client.get.return_value = types.SimpleNamespace(good=True,json={})
        sent = []
        ns['_dispatch'] = sent.append
        values.update({'Commands/Resume':True,'Commands/Stop':True})
        ns['tick'](); ns['tick']()
        self.assertEqual(sent,['Stop'])
        self.assertFalse(values['Commands/Resume'])

    def test_resume_only_uses_dedicated_action(self):
        ns, system, client, values = bridge()
        system.util.invokeAsynchronous.side_effect=lambda fn: fn()
        client.get.return_value=types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Paused'})
        client.post.return_value=types.SimpleNamespace(good=True,json={'result':'Resume accepted'})
        ready(ns,values)
        ns['system_command']('Reset'); ns['system_command']('Start')
        ns['command']('Resume'); ns['_dispatch']('Resume')
        self.assertEqual(client.post.call_args.kwargs['data']['action'],'Resume')
        self.assertFalse(values['Commands/Busy'])








    def test_vision_diagnostics_never_create_commands(self):
        ns, system, client, values = bridge()
        client.get.return_value = types.SimpleNamespace(good=True, json={'online':True,'mqtt_connected':True,'state':'Running'})
        for state in ('Active', 'Clear', 'Unknown', 'Valid'):
            values['[default]vLock/A-101/State'] = state
            ns['tick']()
            self.assertEqual(values['Vision/State'], state)
            self.assertTrue(values['Vision/TagsGood'])
            self.assertFalse(values['Commands/Pause'])
        ns['_test_bad'].add('[default]vLock/A-101/State')
        ns['tick']()
        self.assertFalse(values['Vision/TagsGood'])
        self.assertEqual(values['Vision/State'], 'Unavailable')
        self.assertFalse(values['Commands/Pause'])
        client.post.assert_not_called()
        system.util.invokeAsynchronous.assert_not_called()

    def test_restart_discards_old_requests_without_commands(self):
        ns, system, client, values = bridge()
        values['Commands/Resume'] = True
        ns['_ready'] = False
        ns['initialize']()
        self.assertFalse(values['Commands/Resume'])
        client.post.assert_not_called()

    def test_scada_controls_keep_local_audit_and_reset_never_sends_a_command(self):
        ns, system, client, values = bridge()
        ready(ns,values)
        for action, target in [('Reset','farm'),('Start','farm'),('Stop','farm'),('Reset','P1S-01')]:
            ns['system_command'](action, target)
        doc=json.loads(values['Controls/Request'])
        self.assertEqual(doc['sequence'],4)
        self.assertEqual(doc['counts'], {'Start':1,'Stop':1,'Reset':2})
        self.assertEqual(doc['target'],'P1S-01')
        self.assertEqual(doc['action'],'Reset')
        self.assertIn('Latch reset',values['Controls/Message'])
        client.post.assert_not_called()
        client.get.assert_not_called()
        self.assertFalse(values['Commands/Pause'])

    def test_scada_request_can_be_disabled_by_deployment_setting(self):
        ns, system, client, values = bridge()
        before=values['Controls/Request']
        values['Config/ControlRequestsEnabled']=False
        with self.assertRaises(ValueError): ns['system_command']('Start')
        self.assertEqual(values['Controls/Request'],before)
        with self.assertRaises(ValueError): ns['system_command']('Restart')

    def test_job_fields_and_missing_values(self):
        ns, system, client, values = bridge()
        client.get.return_value = types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Running','progress':45,'remaining_seconds':122,'file_name':'demo.3mf'})
        ns['_dispatch'] = lambda action: None
        ns['tick']()
        self.assertEqual(values['Readings/FileName'], 'demo.3mf')
        self.assertTrue(values['Readings/ProgressValid'])
        self.assertEqual(values['Readings/RemainingSeconds'], 122)
        client.get.return_value.json.update(progress=101, remaining_seconds=float('nan'))
        ns['tick']()
        self.assertFalse(values['Readings/ProgressValid'])
        self.assertFalse(values['Readings/RemainingValid'])

    def test_events_are_bounded_and_only_record_state_changes(self):
        ns, system, client, values = bridge()
        for n in range(40): ns['_event']('Event ' + str(n))
        events = json.loads(values['System/Events'])
        self.assertEqual(len(events),25)
        self.assertEqual(events[0]['event'], 'Event 39')

    def test_camera_uses_original_bytes_and_clears_on_failure(self):
        ns, system, client, values = bridge()
        jpeg = b'\xff\xd8test\xff\xd9'
        client.get.return_value = types.SimpleNamespace(good=True, body=jpeg)
        self.assertEqual(ns['camera_snapshot']()['source'], 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode())
        client.get.return_value.good = False
        self.assertEqual(ns['camera_snapshot']()['source'], '')
        client.get.assert_called_with('http://127.0.0.1:8876/camera.jpg', timeout=750)


class ExportTests(unittest.TestCase):

    def test_camera_off_stops_requests_and_rejects_a_late_frame(self):
        view=json.loads((HERE/'project/com.inductiveautomation.perspective/views/PrinterFarm/Dashboard/view.json').read_text(encoding='utf-8'))
        def find(node):
            if node['meta']['name']=='CameraImage' and node.get('propConfig'): return node
            for child in node.get('children',[]):
                result=find(child)
                if result: return result
        node=find(view['root'])
        code=node['propConfig']['props.source']['binding']['transforms'][0]['code']
        snapshot=Mock(return_value={'source':'fresh-jpeg','message':'Connected'})
        ns={'bambuP1s':types.SimpleNamespace(camera_snapshot=snapshot)}
        exec('def transform(self):\n'+code,ns)
        custom=types.SimpleNamespace(cameraEnabled=False,cameraMessage='')
        component=types.SimpleNamespace(view=types.SimpleNamespace(custom=custom),
            parent=types.SimpleNamespace(custom=types.SimpleNamespace(placeholder='unavailable',offPlaceholder='off')))
        self.assertEqual(ns['transform'](component),'off')
        snapshot.assert_not_called()
        custom.cameraEnabled=True
        self.assertEqual(ns['transform'](component),'fresh-jpeg')
        def late_frame():
            custom.cameraEnabled=False
            return {'source':'late-jpeg','message':'Connected'}
        snapshot.side_effect=late_frame
        self.assertEqual(ns['transform'](component),'off')
        self.assertEqual(custom.cameraMessage,'Camera off')

    def test_resources_bindings_and_naming(self):
        with ZipFile(HERE/'output/printer-farm-perspective.zip') as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                data=archive.read(name).decode('utf-8')
                if name.endswith('.json'):
                    obj=json.loads(data)
                    if name.endswith('/resource.json'):
                        for f in obj['files']:
                            self.assertIn(name.rsplit('/',1)[0]+'/'+f,archive.namelist())
                elif name.endswith('.py'): ast.parse(data)
        tags=json.loads((HERE/'output/bambu-p1s-tags.json').read_text())
        paths=set()
        def walk(nodes,prefix='[default]'):
            for n in nodes:
                path=prefix+n['name']
                if 'tags' in n: walk(n['tags'],path+'/')
                else: paths.add(path)
        walk(tags['tags'])
        view=(HERE/'project/com.inductiveautomation.perspective/views/PrinterFarm/Dashboard/view.json').read_text()
        for path in re.findall(r'\{(\[default\][^}]+)\}',view): self.assertIn(path,paths)
        self.assertNotIn("bambuP1s.command('Start')",view)
        obj=json.loads(view)
        def nodes(n):
            yield n
            for c in n.get('children',[]): yield from nodes(c)
        all_nodes=list(nodes(obj['root']))
        for name in ('Printer02', 'Printer03'):
            offline=next(n for n in all_nodes if n['meta']['name']==name)
            for node in nodes(offline):
                self.assertNotIn('events', node)
                self.assertNotIn('propConfig', node)
                if node['type']=='ia.input.button': self.assertFalse(node['props']['enabled'])
        self.assertIn('CameraPanel', view)
        for name in ('SystemStart', 'SystemStop', 'SystemReset', 'PrinterReset'):
            node=next(n for n in all_nodes if n['meta']['name']==name)
            self.assertIn('events', node)
            self.assertIn('Config/ControlRequestsEnabled',str(node['propConfig']))
        for node in all_nodes:
            for binding in node.get('propConfig', {}).values():
                expr=binding.get('binding',{}).get('config',{}).get('expression','')
                if node['type']=='ia.input.button': self.assertNotIn('Vision/',expr)
        self.assertIn('System/ResumeAllowed',view)
        with ZipFile(HERE/'output/printer-farm-perspective.zip') as archive:
            legacy=json.loads(archive.read('ignition/tag-change/PauseOnDetection/resource.json'))
            self.assertFalse(legacy['attributes']['enabled'])
            self.assertNotIn('command(',archive.read('ignition/tag-change/PauseOnDetection/onTagChange.py').decode())
            timer=json.loads(archive.read('ignition/timer/printerSiteTick/resource.json'))
            self.assertEqual(timer['attributes']['delay'],250)
            self.assertFalse(timer['attributes']['sharedThread'])

    def test_connector_resume_guard(self):
        spec=importlib.util.spec_from_file_location('resume_patch',HERE/'enable_resume.py')
        patch=importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)
        source=(HERE/'connector/p1s_service.py').read_text(encoding='utf-8-sig')
        updated=patch.patched(source)
        self.assertEqual(patch.patched(updated),updated)
        tree=ast.parse(updated)
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_execute')
        method=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
        class UserError(Exception): pass
        ns=dict(UserError=UserError,threading=threading,json=json)
        exec(compile(method,'<connector>','exec'),ns)
        sent=[]
        class Printer:
            def __init__(self,state):
                self.state=state
                self.client=types.SimpleNamespace(publish=self.publish)
                self.pending={}; self.pending_lock=threading.Lock()
                self.stop_event=threading.Event()
                self.telemetry=types.SimpleNamespace(lock=threading.Lock())
                self.config=types.SimpleNamespace(serial='TESTSERIAL')
                self.clock=time.monotonic
            def publish(self,topic,payload,**kwargs):
                sent.append(json.loads(payload))
                self.pending['seq']['reply']={'result':'SUCCESS'}
                return types.SimpleNamespace(rc=0)
            def status(self): return {'online':True,'state':self.state,'revision':1,'fault':False}
            def next_sequence(self): return 'seq'
        for state in ('Idle','Running','Completed'):
            with self.assertRaises(UserError): ns['_execute'](Printer(state),'Resume')
        self.assertFalse(sent)
        ns['_execute'](Printer('Paused'),'Resume')
        self.assertEqual(sent[0]['print']['command'],'resume')


if __name__=='__main__': unittest.main()
