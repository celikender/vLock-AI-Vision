import importlib.util,json,pathlib,tempfile,threading,time,types,unittest,urllib.request,urllib.error,struct
from unittest.mock import patch
B=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('p1s_service',B/'connector/p1s_service.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class FakeClock:
 def __init__(self):self.value=100.0
 def __call__(self):return self.value
class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.clock=FakeClock();self.values={'BAMBU_IP':'192.168.1.100','BAMBU_SERIAL':'01S_TEST_SERIAL','BAMBU_ACCESS_CODE':'TESTCODE','BAMBU_FILAMENT_SOURCE':'external','BAMBU_PRINT_FILE':'part.gcode.3mf'}
  self.config=m.Config(self.values,self.tmp.name);self.a=m.Adapter(self.config,clock=self.clock)
 def tearDown(self):self.tmp.cleanup()
 def report(self,**kwargs):
  self.a.telemetry.connection(True);self.a.telemetry.update(dict({'gcode_state':'IDLE','nozzle_temper':24,'bed_temper':25},**kwargs))
 def client(self,reply='SUCCESS',state=None,rc=0):
  a=self.a;sent=[]
  def publish(topic,payload,**kw):
   body=json.loads(payload)['print'];sent.append((topic,body,kw))
   if state:a.telemetry.update({'gcode_state':state})
   if reply is not None:
    msg={'print':{'sequence_id':body['sequence_id'],'command':body['command'],'result':reply}}
    if reply!='SUCCESS':msg['print']['reason']='Authorization rejected'
    a.on_message(None,None,types.SimpleNamespace(payload=json.dumps(msg).encode()))
   return types.SimpleNamespace(rc=rc)
  a.client=types.SimpleNamespace(publish=publish);return sent
 def test_no_credentials_means_offline_not_demo(self):
  c=m.Config({'BAMBU_IP':'192.168.1.100'},self.tmp.name);a=m.Adapter(c);a.start();s=a.status();self.assertFalse(s['online']);self.assertFalse(s['configured']);self.assertIsNone(s['nozzle_temp']);self.assertEqual([],a.threads)
 def test_env_preserves_equals_and_quotes(self):
  p=pathlib.Path(self.tmp.name)/'.env';p.write_text('# comment\nA="hello world"\nB=x=y\n');self.assertEqual({'A':'hello world','B':'x=y'},m.read_env(p))
 def test_ip_not_shell_or_url(self):
  with self.assertRaises(ValueError):m.Config({'BAMBU_IP':'http://evil.example/'})
 def test_serial_rejects_mac_punctuation(self):
  with self.assertRaises(ValueError):m.Config(dict(self.values,BAMBU_SERIAL='AA:BB:CC:DD:EE:FF'))
 def test_unknown_fields_are_not_zero_filled(self):
  self.a.telemetry.connection(True);self.a.telemetry.update({'gcode_state':'IDLE'});s=self.a.status();self.assertTrue(s['online']);self.assertIsNone(s['nozzle_temp']);self.assertIsNone(s['progress']);self.assertIsNone(s['filament_remaining'])
 def test_online_requires_actual_status_not_mqtt_alone(self):
  self.a.telemetry.connection(True);self.assertFalse(self.a.status()['online'])
 def test_partial_delta_merge(self):
  self.report();self.a.telemetry.update({'mc_percent':62});s=self.a.status();self.assertEqual(24,s['nozzle_temp']);self.assertEqual(62,s['progress'])
 def test_connection_loss_hides_old_values(self):
  self.report();self.a.telemetry.connection(False);s=self.a.status();self.assertFalse(s['online']);self.assertIsNone(s['nozzle_temp']);self.assertEqual('Offline',s['state'])
 def test_reconnect_does_not_reuse_old_values(self):
  self.report(mc_percent=50);self.a.telemetry.connection(False);self.a.telemetry.connection(True);self.a.telemetry.update({'gcode_state':'IDLE'});self.assertIsNone(self.a.status()['progress'])
 def test_stale_data_goes_offline(self):
  self.report();self.clock.value+=31;self.assertFalse(self.a.status()['online']);self.assertIsNone(self.a.status()['bed_temp'])
 def test_all_real_state_mappings(self):
  for raw,state in [('IDLE','Idle'),('RUNNING','Running'),('PREPARE','Running'),('PAUSE','Paused'),('FINISH','Completed'),('FAILED','Fault')]:
   self.a.telemetry.connection(True);self.a.telemetry.update({'gcode_state':raw});self.assertEqual(state,self.a.status()['state'])
 def test_unknown_state_is_not_idle(self):
  self.a.telemetry.connection(True);self.a.telemetry.update({'nozzle_temper':22});self.assertEqual('Unknown',self.a.status()['state'])
 def test_eta_converts_minutes_to_seconds(self):
  self.report(mc_remaining_time=12);self.assertEqual(720,self.a.status()['remaining_seconds'])
 def test_invalid_numeric_values_are_unavailable(self):
  self.report(mc_percent=float('nan'),mc_remaining_time=-1);self.assertIsNone(self.a.status()['progress']);self.assertIsNone(self.a.status()['remaining_seconds']);self.assertIsNone(m.numeric(True))
 def test_ams_delta_merges_units_and_trays_by_id(self):
  self.report();self.a.telemetry.update({'ams':{'tray_now':'1','ams':[{'id':'0','tray':[{'id':'0','remain':90},{'id':'1','remain':50}]}]}});self.a.telemetry.update({'ams':{'ams':[{'id':'0','tray':[{'id':'1','remain':48}]}]}});self.assertEqual(48,self.a.status()['filament_remaining']);self.assertEqual(2,len(self.a.telemetry.data['ams']['ams'][0]['tray']))
 def test_external_spool_is_not_estimated(self):
  self.report(ams={'tray_now':'254','ams':[{'id':'0','tray':[{'id':'0','remain':50}]}]});self.assertIsNone(self.a.status()['filament_remaining'])
 def test_zero_error_strings_do_not_trigger_fault(self):
  for zero in [0,'0','0x00000000','00000000']:
   self.report(print_error=zero);self.assertFalse(self.a.status()['fault'])
 def test_real_print_error_is_reported(self):
  self.report(print_error=1234);self.assertTrue(self.a.status()['fault']);self.assertIn('1234',self.a.status()['fault_message'])
 def test_ack_packet_does_not_establish_online(self):
  self.a.telemetry.connection(True);msg=types.SimpleNamespace(payload=b'{"print":{"command":"pause","result":"SUCCESS","sequence_id":"1"}}');self.a.on_message(None,None,msg);self.assertFalse(self.a.status()['online'])
 def test_invalid_packet_ignored(self):
  self.a.on_message(None,None,types.SimpleNamespace(payload=b'not JSON'));self.assertFalse(self.a.status()['online'])
 def test_json_array_report_is_ignored(self):
  self.a.on_message(None,None,types.SimpleNamespace(payload=b'[]'));self.assertFalse(self.a.status()['online'])
 def test_malformed_ams_does_not_break_status(self):
  self.report(ams={'tray_now':'0','ams':[None,{'id':'0','tray':None}]});self.assertTrue(self.a.status()['online']);self.assertIsNone(self.a.status()['filament_remaining'])
 def test_camera_auth_packet(self):
  packet=m.camera_auth('TESTCODE');self.assertEqual(80,len(packet));fields=struct.unpack('<IIII32s32s',packet);self.assertEqual(0x40,fields[0]);self.assertEqual(0x3000,fields[1]);self.assertEqual(b'bblp',fields[4].rstrip(b'\0'));self.assertEqual(b'TESTCODE',fields[5].rstrip(b'\0'))
 def test_camera_fragmented_reads(self):
  blocks=iter([b'aa',b'b',b'cc']);self.assertEqual(b'aabcc',m.recv_exact(types.SimpleNamespace(recv=lambda n:next(blocks)),5))
 def test_camera_eof(self):
  with self.assertRaises(EOFError):m.recv_exact(types.SimpleNamespace(recv=lambda n:b''),16)
 def test_camera_expiry_hides_image(self):
  c=self.a.camera;c.frame=b'jpeg';c.when=self.clock();self.assertIsNotNone(c.latest()[0]);self.clock.value+=11;self.assertIsNone(c.latest()[0])
 def test_camera_clear_drops_cache(self):
  c=self.a.camera;c.frame=b'jpeg';c.when=self.clock();c.clear();self.assertIsNone(c.latest()[0])
 def test_start_file_payload_is_explicit(self):
  p=self.config.job_payload('123')['print'];self.assertEqual('project_file',p['command']);self.assertEqual('ftp:///part.gcode.3mf',p['url']);self.assertEqual('Metadata/plate_1.gcode',p['param']);self.assertFalse(p['use_ams'])
 def test_no_new_job_without_selected_file(self):
  c=m.Config(dict(self.values,BAMBU_PRINT_FILE=''),self.tmp.name)
  with self.assertRaises(m.UserError):c.job_payload('123')
 def test_no_new_job_with_unset_filament_source(self):
  c=m.Config(dict(self.values,BAMBU_FILAMENT_SOURCE='unset'),self.tmp.name)
  with self.assertRaises(m.UserError):c.job_payload('123')
 def test_ams_requires_mapping(self):
  c=m.Config(dict(self.values,BAMBU_FILAMENT_SOURCE='ams'),self.tmp.name)
  with self.assertRaises(m.UserError):c.job_payload('123')
 def test_ams_payload_uses_explicit_mapping(self):
  c=m.Config(dict(self.values,BAMBU_FILAMENT_SOURCE='ams',BAMBU_AMS_MAPPING='[0]'),self.tmp.name);self.assertEqual([0],c.job_payload('1')['print']['ams_mapping'])
 def test_path_traversal_and_urls_rejected(self):
  for filename in ['../part.gcode.3mf','/part.gcode.3mf','http://foo/part.gcode.3mf','part.gcode']:
   c=m.Config(dict(self.values,BAMBU_PRINT_FILE=filename),self.tmp.name)
   with self.assertRaises(m.UserError):c.job_payload('1')
 def test_start_sends_selected_real_job(self):
  self.report();sent=self.client();r=self.a.execute('Start','unique001');self.assertTrue(r['accepted']);self.assertEqual('project_file',sent[0][1]['command']);self.assertEqual('Idle',self.a.status()['state'])
 def test_resume_does_not_need_new_job_configuration(self):
  self.a.config.print_file='';self.a.telemetry.connection(True);self.a.telemetry.update({'gcode_state':'PAUSE'});sent=self.client();self.a.execute('Start','unique002');self.assertEqual('resume',sent[0][1]['command'])
 def test_pause_and_stop(self):
  for action,expected in [('Pause','pause'),('Stop','stop')]:
   self.a.telemetry.connection(True);self.a.telemetry.update({'gcode_state':'RUNNING'});sent=self.client();self.a.execute(action,'request'+action);self.assertEqual(expected,sent[0][1]['command']);self.assertFalse(sent[0][2]['retain'])
 def test_command_ack_does_not_fabricate_machine_state(self):
  self.report();self.client();self.a.execute('Start','unique003');self.assertEqual('Idle',self.a.status()['state'])
 def test_offline_command_does_not_publish(self):
  sent=self.client()
  with self.assertRaises(m.UserError):self.a.execute('Start','unique004')
  self.assertEqual([],sent)
 def test_printer_rejection_reported(self):
  self.report();self.client(reply='FAIL')
  with self.assertRaisesRegex(m.UserError,'rejected'):self.a.execute('Start','unique005')
 def test_publish_failure_is_not_success(self):
  self.report();self.client(reply=None,rc=4)
  with self.assertRaises(m.UserError):self.a.execute('Start','unique006')
 def test_state_transition_can_confirm_without_ack(self):
  self.report();self.client(reply=None,state='RUNNING');r=self.a.execute('Start','unique007');self.assertIn('live printer state',r['result'])
 def test_no_ack_reports_unknown_outcome(self):
  self.report();self.client(reply=None)
  old_wait=threading.Event.wait
  def advance(event,timeout=None):self.clock.value+=4;return False
  with patch.object(threading.Event,'wait',advance):
   with self.assertRaisesRegex(m.UserError,'outcome unknown'):self.a.execute('Start','unique008')
 def test_same_id_does_not_replay_command(self):
  self.report();sent=self.client();self.a.execute('Start','unique009');self.a.execute('Start','unique009');self.assertEqual(1,len(sent))
 def test_id_cannot_be_reused_for_different_action(self):
  self.report();self.client();self.a.execute('Start','unique010')
  with self.assertRaises(m.UserError):self.a.execute('Stop','unique010')
 def test_reset_reconnects_without_printer_commands(self):
  self.report(print_error=123);sent=self.client();r=self.a.execute('Reset','unique011');self.assertTrue(self.a.reset_event.is_set());self.assertFalse(self.a.status()['online']);self.assertEqual([],sent);self.assertEqual('Reconnecting',r['result'])
 def test_credentials_not_in_status(self):
  self.assertNotIn('TESTCODE',json.dumps(self.a.status()));self.assertNotIn('BAMBU_ACCESS_CODE',json.dumps(self.a.status()))
 def test_real_tls_pinning_rejects_changed_certificate(self):
  import ssl,socket
  from datetime import datetime,timedelta,timezone
  from cryptography import x509
  from cryptography.hazmat.primitives import hashes,serialization
  from cryptography.hazmat.primitives.asymmetric import rsa
  root=pathlib.Path(self.tmp.name)
  def make_pair(n):
   cert=root/(str(n)+'.pem');key=root/(str(n)+'.key')
   private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
   name=x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME,'test-printer-'+str(n))])
   now=datetime.now(timezone.utc)
   certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
      .public_key(private.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
      .sign(private,hashes.SHA256()))
   cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
   key.write_bytes(private.private_bytes(serialization.Encoding.PEM,
      serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
   return cert,key
  def connect(pair,client):
   cert,key=pair;context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
   listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(4)
   def worker():
    try:
     raw,addr=listener.accept()
     with context.wrap_socket(raw,server_side=True) as secure:
      try:secure.sendall(b'ok')
      except OSError:pass
    except OSError:pass
    finally:listener.close()
   thread=threading.Thread(target=worker,daemon=True);thread.start()
   try:
    with socket.create_connection(listener.getsockname(),timeout=3) as raw:
     with client.wrap_socket(raw,server_hostname='127.0.0.1') as secure:return secure.recv(2)
   finally:thread.join(5)
  client=m.PinnedTLS(root/'pins'/'printer.sha256');pair=make_pair(1)
  self.assertEqual(b'ok',connect(pair,client));self.assertTrue((root/'pins'/'printer.sha256').exists())
  self.assertEqual(b'ok',connect(pair,client))
  with self.assertRaisesRegex(ssl.SSLError,'certificate changed'):connect(make_pair(2),client)
 def test_loopback_http_status_and_camera(self):
  server=m.Server(self.a,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
  try:
   with urllib.request.urlopen(base+'/status') as r:s=json.load(r)
   self.assertFalse(s['online']);self.assertIsNone(s['nozzle_temp'])
   with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/camera.jpg')
   self.assertEqual(503,error.exception.code)
   self.a.camera.frame=b'\xff\xd8body\xff\xd9';self.a.camera.when=self.clock()
   with urllib.request.urlopen(base+'/camera.jpg') as r:self.assertEqual('image/jpeg',r.headers['Content-Type']);self.assertEqual(self.a.camera.frame,r.read())
   request=urllib.request.Request(base+'/status',headers={'Origin':'https://example.org'})
   with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
   self.assertEqual(403,error.exception.code)
   request=urllib.request.Request(base+'/command',data=b'action=Start',headers={'Content-Type':'application/x-www-form-urlencoded'})
   with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
   self.assertEqual(415,error.exception.code)
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main(verbosity=2)
