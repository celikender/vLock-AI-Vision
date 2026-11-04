"""Offline contract checks; never connects to or commands the real printer."""
import ast
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


class Lock:
    def tryLock(self): return True
    def unlock(self): pass


def bridge():
    tree = ast.parse((HERE / 'project/ignition/script-python/bambuP1s/code.py').read_text())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    values = {}
    client = Mock()
    system = Mock()
    system.net.httpClient.return_value = client
    system.tag.writeBlocking.side_effect = lambda paths, vals, timeout: [values.__setitem__(p.split('BambuP1S/')[1], v) or Mock(isGood=lambda: True) for p,v in zip(paths, vals)]
    system.tag.readBlocking.side_effect = lambda paths, timeout: [types.SimpleNamespace(value=values.get(p.split('BambuP1S/')[1], False), quality=Mock(isGood=lambda: True)) for p in paths]
    system.tag.exists.return_value = True
    namespace = dict(system=system, math=math, re=re, long=int, AtomicBoolean=Atomic, ReentrantLock=Lock, UUID=Mock(randomUUID=lambda: 'test-request-123'))
    exec(compile(tree, '<bridge>', 'exec'), namespace)
    namespace['initialize']()
    values['Config/ServiceUrl'] = 'http://127.0.0.1:8876'
    return namespace, system, client, values


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

    def test_system_controls_never_send_printer_commands(self):
        ns, system, client, values = bridge()
        for action in ('Start','Stop','Reset'):
            ns['system_command'](action)
            self.assertEqual(values['System/Enabled'],action=='Start')
        client.post.assert_not_called()
        client.get.assert_not_called()

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
        ns['_dispatch']('Resume')
        client.post.assert_not_called()
        values['System/Enabled']=True
        ns['_dispatch']('Resume')
        self.assertEqual(client.post.call_args.kwargs['data']['action'],'Resume')
        self.assertFalse(values['Commands/Busy'])


class ExportTests(unittest.TestCase):
    def test_resources_bindings_and_naming(self):
        with ZipFile(HERE/'output/single-printer-perspective.zip') as archive:
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
        self.assertNotIn('CameraPanel',view)

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
