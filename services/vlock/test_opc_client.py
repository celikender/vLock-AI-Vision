"""Client contract checks against isolated local endpoints, never machine tags."""
import asyncio
import copy
import importlib.util
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.vlock.store import BridgeError, Store
from services.vlock.transports import DEFAULTS, Integrations, configuration
from services.vlock.opc_client import OpcUaClient
from services.vlock.test_transports import free_port


class ClientConfigurationTests(unittest.TestCase):
    def test_old_settings_migrate_without_enabling_client(self):
        old = copy.deepcopy(DEFAULTS)
        old['opcua'] = {'enabled': True, 'port': 4845}
        result = configuration(old)
        self.assertEqual(result['opcua'], DEFAULTS['opcua'] | old['opcua'])
        self.assertEqual(result['opcua']['mode'], 'server')

    def test_invalid_mappings_and_nonlocal_endpoints_rejected(self):
        cases = [
            {'endpoint': 'opc.tcp://192.168.1.2:62541'},
            {'endpoint': 'opc.tcp://user:secret@127.0.0.1:62541'},
            {'endpoint': 'http://127.0.0.1:62541'},
            {'endpoint': 'opc.tcp://127.0.0.1:4845'},
            {'reads': [{'label': 'running', 'node_id': 'wrong'}]},
            {'writes': [{'asset_id': 'machine', 'field': 'inhibit', 'node_id': 'ns=2;s=X'}]},
            {'writes': [{'asset_id': 'machine', 'field': 'state_json', 'node_id': 'ns=2;s=X'}]},
            {'reads': [{'label': 'same', 'node_id': 'i=1'}] * 2},
            {'heartbeat_node_id': 'i=1', 'reads': [{'label': 'loop', 'node_id': 'i=1'}]},
            {'heartbeat_node_id': 'i=1', 'writes': [{'asset_id': 'machine', 'field': 'state_json', 'node_id': 'i=1'}]},
            {'password': 'must-not-be-saved'},
        ]
        for change in cases:
            with self.subTest(change=change):
                settings = copy.deepcopy(DEFAULTS)
                settings['opcua'].update(mode='client', **change)
                with self.assertRaises(BridgeError):
                    configuration(settings)


@unittest.skipUnless(importlib.util.find_spec('asyncua'), 'Install requirements.txt for OPC UA checks.')
class ClientExchangeTests(unittest.TestCase):
    def test_rejected_write_does_not_advance_heartbeat_or_claim_online(self):
        asyncio.run(self.rejected_write())

    async def rejected_write(self):
        from asyncua import Server, ua
        logging.getLogger('asyncua').setLevel(logging.CRITICAL)
        server = Server()
        await server.init()
        server.set_endpoint(f'opc.tcp://127.0.0.1:{free_port()}/')
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        index = await server.register_namespace('urn:vlock:write-test')
        target = await server.nodes.objects.add_variable(ua.NodeId('Target', index), 'Target', '', ua.VariantType.String)
        heartbeat = await server.nodes.objects.add_variable(ua.NodeId('Pulse', index), 'Pulse', False, ua.VariantType.Boolean)
        await heartbeat.set_writable()
        settings = DEFAULTS['opcua'] | dict(enabled=True, mode='client', security='None',
            endpoint=server.endpoint.geturl(), heartbeat_node_id=heartbeat.nodeid.to_string(),
            writes=[dict(asset_id='machine', field='state_json', node_id=target.nodeid.to_string())])
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'bridge.sqlite3')
            worker = OpcUaClient(store, settings)
            await server.start()
            try:
                worker.start()
                deadline = time.monotonic() + 10
                while worker.status()['status'] != 'disconnected' and time.monotonic() < deadline:
                    await asyncio.sleep(.05)
                self.assertEqual(worker.status()['status'], 'disconnected')
                self.assertFalse(worker.status()['online'])
                self.assertEqual(worker.status()['heartbeat_counter'], 0)
                self.assertFalse(await heartbeat.read_value())
                self.assertEqual(await target.read_value(), '')
            finally:
                await asyncio.to_thread(worker.stop)
                await server.stop()
                store.close()

    def test_encrypted_username_session_and_wrong_server_certificate(self):
        asyncio.run(self.secure_session())

    async def secure_session(self):
        from asyncua import Server, ua
        from asyncua.crypto import cert_gen
        from asyncua.crypto.permission_rules import User, UserRole
        from cryptography.x509.oid import ExtendedKeyUsageOID
        logging.getLogger('asyncua').setLevel(logging.CRITICAL)
        class TestUsers:
            def get_user(self, iserver, username=None, password=None, certificate=None):
                if username == 'test-reader' and password == 'isolated-test-password':
                    return User(role=UserRole.User)
                return None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, uri, usage in [('server', 'urn:vlock:test:server', ExtendedKeyUsageOID.SERVER_AUTH),
                                      ('client', 'urn:vlock:bridge:client', ExtendedKeyUsageOID.CLIENT_AUTH),
                                      ('other', 'urn:vlock:test:other', ExtendedKeyUsageOID.SERVER_AUTH)]:
                await cert_gen.setup_self_signed_certificate(root / (name + '.pem'), root / (name + '.der'),
                    uri, 'localhost', [usage], {'commonName': name})
            server = Server(user_manager=TestUsers())
            await server.init()
            await server.set_application_uri('urn:vlock:test:server')
            server.set_endpoint(f'opc.tcp://127.0.0.1:{free_port()}/')
            server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
            server.set_identity_tokens([ua.UserNameIdentityToken])
            await server.load_certificate(root / 'server.der')
            await server.load_private_key(root / 'server.pem')
            store = Store(root / 'bridge.sqlite3')
            settings = DEFAULTS['opcua'] | dict(enabled=True, mode='client', endpoint=server.endpoint.geturl())
            environment = dict(VLOCK_BRIDGE_OPCUA_USERNAME='test-reader', VLOCK_BRIDGE_OPCUA_PASSWORD='isolated-test-password',
                VLOCK_BRIDGE_OPCUA_CERTIFICATE=str(root / 'client.der'), VLOCK_BRIDGE_OPCUA_PRIVATE_KEY=str(root / 'client.pem'),
                VLOCK_BRIDGE_OPCUA_SERVER_CERTIFICATE=str(root / 'server.der'))
            await server.start()
            worker = None
            try:
                with patch.dict('os.environ', environment):
                    worker = OpcUaClient(store, settings)
                    worker.start()
                    deadline = time.monotonic() + 10
                    while not worker.status()['online'] and time.monotonic() < deadline:
                        await asyncio.sleep(.05)
                    self.assertTrue(worker.status()['online'])
                    await asyncio.to_thread(worker.stop)
                    with patch.dict('os.environ', {'VLOCK_BRIDGE_OPCUA_SERVER_CERTIFICATE': str(root / 'other.der')}):
                        worker = OpcUaClient(store, settings)
                        worker.start()
                        deadline = time.monotonic() + 8
                        while worker.status()['status'] not in ('disconnected', 'error') and time.monotonic() < deadline:
                            await asyncio.sleep(.05)
                        self.assertFalse(worker.status()['online'])
                        self.assertIn(worker.status()['status'], ('disconnected', 'error'))
            finally:
                if worker:
                    await asyncio.to_thread(worker.stop)
                await server.stop()
                store.close()

    def test_roundtrip_quality_expiry_disconnect_and_reconnect(self):
        asyncio.run(self.roundtrip())

    async def roundtrip(self):
        from asyncua import Server, ua
        logging.getLogger('asyncua').setLevel(logging.CRITICAL)
        port = free_port()
        server = Server()
        await server.init()
        server.set_endpoint(f'opc.tcp://127.0.0.1:{port}/')
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        index = await server.register_namespace('urn:vlock:client-test')
        folder = await server.nodes.objects.add_object(index, 'Test')
        async def variable(name, value, variant):
            node = await folder.add_variable(ua.NodeId(name, index), name, value, variant)
            await node.set_writable()
            return node
        running = await variable('Running', True, ua.VariantType.Boolean)
        inhibit = await variable('Inhibit', False, ua.VariantType.Boolean)
        known = await variable('Known', True, ua.VariantType.Boolean)
        document = await variable('State', '', ua.VariantType.String)
        heartbeat = await variable('Heartbeat', False, ua.VariantType.Boolean)
        def nid(name):
            return 'nsu=urn:vlock:client-test;s=' + name
        settings = copy.deepcopy(DEFAULTS['opcua']) | dict(enabled=True, mode='client',
            endpoint=f'opc.tcp://127.0.0.1:{port}/', security='None',
            reads=[dict(label='running', node_id=nid('Running'))],
            writes=[dict(asset_id='machine', field='inhibit', node_id=nid('Inhibit'), known_node_id=nid('Known')),
                    dict(asset_id='machine', field='state_json', node_id=nid('State'))],
            heartbeat_node_id=nid('Heartbeat'))
        async def until(predicate, seconds=15):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                result = await predicate()
                if result:
                    return result
                await asyncio.sleep(.05)
            self.fail('Expected isolated OPC UA exchange was not observed.')
        async def state_status(expected):
            text = await document.read_value()
            return text and json.loads(text).get('observation_status') == expected
        with tempfile.TemporaryDirectory() as directory:
            now = [time.time()]
            store = Store(Path(directory) / 'bridge.sqlite3', clock=lambda: now[0])
            manager = None
            await server.start()
            try:
                manager = Integrations(store, Path(directory) / 'transports.json')
                manager.apply(copy.deepcopy(DEFAULTS) | {'opcua': settings})
                worker = manager.workers['opcua']
                self.assertIsInstance(worker, OpcUaClient)
                await until(lambda: state_status('unknown'))
                self.assertFalse(await known.read_value())
                sample = dict(asset_id='machine', source_id='manual', signal_id='presence', status='active')
                store.submit(sample)
                await until(lambda: state_status('active'))
                self.assertTrue(await inhibit.read_value())
                self.assertTrue(await known.read_value())
                self.assertEqual(worker.status()['reads'][0]['value'], True)
                self.assertTrue(worker.status()['reads'][0]['available'])
                self.assertIsNotNone(worker.status()['reads'][0]['source_timestamp'])
                first_pulse = await heartbeat.read_value()
                async def changed_pulse():
                    return await heartbeat.read_value() != first_pulse
                await until(changed_pulse)
                bad = ua.DataValue(ua.Variant(False, ua.VariantType.Boolean),
                                   StatusCode=ua.StatusCode(ua.StatusCodes.BadNoCommunication))
                await running.write_value(bad)
                async def bad_read():
                    return worker.status()['online'] and worker.status()['reads'][0]['quality'] == 'BadNoCommunication'
                await until(bad_read)
                self.assertIsNone(worker.status()['reads'][0]['value'])
                self.assertFalse(worker.status()['reads'][0]['available'])
                now[0] += 31
                await until(lambda: state_status('stale'))
                self.assertFalse(await known.read_value())
                self.assertTrue(await inhibit.read_value())  # Unknown never fabricates Clear.
                now[0] += 1
                store.submit(sample | {'status': 'clear'})
                await until(lambda: state_status('clear'))
                self.assertFalse(await inhibit.read_value())
                self.assertTrue(await known.read_value())
                await server.stop()
                async def offline():
                    return not worker.status()['online']
                await until(offline)
                self.assertIsNone(worker.status()['reads'][0]['value'])
                now[0] += 31
                # Reconnect must publish expiry, never replay the former valid Clear.
                await server.start()
                await until(lambda: state_status('stale'))
                self.assertFalse(await known.read_value())
                self.assertEqual(len(store.snapshot()['assets'][0]['signals']), 1)
            finally:
                if manager:
                    await asyncio.to_thread(manager.close)
                await server.stop()
                store.close()

    def test_status_hides_frozen_readbacks(self):
        worker = OpcUaClient(None, {})
        worker.state['reads'] = [dict(value=True, available=True, quality='Good')]
        worker.report('connected', 'test', updated=True)
        worker.last_progress -= 6
        self.assertFalse(worker.status()['reads'][0]['available'])
        self.assertIsNone(worker.status()['reads'][0]['value'])


if __name__ == '__main__':
    unittest.main()
