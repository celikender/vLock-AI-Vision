"""Real local MQTT/OPC UA checks; never use the owner's broker or machine."""
import asyncio
import copy
import importlib.util
import json
import logging
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from store import BridgeError, Store
from transports import DEFAULTS, NAMESPACE, Integrations, MqttPublisher, OpcUaServer, configuration


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def until(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Expected local transport state was not observed before timeout.')


class ConfigurationTests(unittest.TestCase):
    def test_adapter_online_requires_recent_progress(self):
        worker = MqttPublisher(None, {})
        with patch('transports.time.monotonic', return_value=100.):
            worker.report('connected', 'test', updated=True)
        with patch('transports.time.monotonic', return_value=104.):
            self.assertTrue(worker.status()['online'])
        with patch('transports.time.monotonic', return_value=105.):
            self.assertFalse(worker.status()['online'])
            self.assertEqual(worker.status()['status'], 'stale')
            self.assertEqual(worker.status()['heartbeat_counter'], 1)
            worker.report('connected', 'test', updated=True)
            self.assertTrue(worker.status()['online'])
            self.assertEqual(worker.status()['heartbeat_counter'], 2)
        worker.report('disconnected', 'test')
        self.assertFalse(worker.status()['online'])

    def test_validation_blocks_remote_hosts_wildcards_and_port_conflicts(self):
        for section, field, value in [('mqtt', 'host', 'example.com'), ('mqtt', 'topic_prefix', 'vlock/#'),
                                      ('mqtt', 'port', True), ('opcua', 'port', 80),
                                      ('opcua', 'port', 1883), ('mqtt', 'enabled', 'yes')]:
            settings = copy.deepcopy(DEFAULTS)
            settings[section][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(BridgeError):
                configuration(settings)

    def test_settings_persist_and_corrupt_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transports.json'
            store = Store(Path(directory) / 'bridge.sqlite3')
            manager = Integrations(store, path)
            try:
                settings = copy.deepcopy(DEFAULTS)
                settings['mqtt']['topic_prefix'] = 'experiment/v1'
                manager.apply(settings)
                manager.close()
                manager = Integrations(store, path)
                self.assertEqual(manager.status()['settings'], settings)
                manager.close()
                path.write_text('broken configuration', encoding='utf-8')
                manager = Integrations(store, path)
                self.assertIsNotNone(manager.status()['settings_error'])
                self.assertEqual(path.read_text(), 'broken configuration')
            finally:
                manager.close()
                store.close()


class LocalBroker:
    def __init__(self, port=None):
        self.port = port or free_port()
        self.ready = threading.Event()
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=lambda: asyncio.run(self.run()), daemon=True)

    async def run(self):
        from amqtt.broker import Broker
        try:
            broker = Broker({'listeners': {'default': {'type': 'tcp', 'bind': f'127.0.0.1:{self.port}'}},
                'plugins': {'amqtt.plugins.authentication.AnonymousAuthPlugin': {'allow_anonymous': True}}})
            await broker.start()
            self.ready.set()
            while not self.stop_event.is_set():
                await asyncio.sleep(.05)
            await broker.shutdown()
        except Exception as error:
            self.error = error
            self.ready.set()

    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise AssertionError('Isolated test broker failed to start.') from self.error

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AssertionError('Isolated test broker did not stop.')


@unittest.skipUnless(importlib.util.find_spec('amqtt') and importlib.util.find_spec('paho'), 'Install requirements-test.txt for MQTT checks.')
class MqttTests(unittest.TestCase):
    def test_delivery_expiry_reconnect_and_offline_availability(self):
        import paho.mqtt.client as mqtt
        logging.getLogger('amqtt').setLevel(logging.CRITICAL)
        broker = LocalBroker()
        broker.start()
        prefix = 'bridge-test/' + uuid4().hex
        latest = {}
        message_lock = threading.Lock()

        def receive(client, userdata, message):
            with message_lock:
                latest[message.topic] = json.loads(message.payload)

        def current(topic):
            with message_lock:
                return latest.get(prefix + '/' + topic)

        subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        subscriber.on_connect = lambda client, userdata, flags, reason, properties: client.subscribe(prefix + '/#', qos=1)
        subscriber.on_message = receive
        subscriber.connect('127.0.0.1', broker.port)
        subscriber.loop_start()
        with tempfile.TemporaryDirectory() as directory:
            now = [time.time()]
            store = Store(Path(directory) / 'bridge.sqlite3', clock=lambda: now[0])
            sample = dict(asset_id='conveyor_01', source_id='manual', signal_id='presence', status='active')
            store.submit(sample)
            store.submit(dict(asset_id='conveyor_01', source_id='manual', signal_id='count', kind='measurement', status='valid', value=12))
            worker = MqttPublisher(store, dict(enabled=True, host='127.0.0.1', port=broker.port, topic_prefix=prefix))
            worker.start()
            try:
                until(lambda: current('assets/conveyor_01/state') and current('assets/conveyor_01/state')['inhibit'] is True)
                state = current('state')
                self.assertEqual(state['assets'][0]['signals'][0]['value'], 12)
                until(lambda: worker.status()['status'] == 'connected')
                self.assertIsNotNone(worker.status()['last_update'])
                available = until(lambda: current('availability'))
                self.assertTrue(available['online'])
                self.assertIsInstance(available['heartbeat_pulse'], bool)
                first_counter = available['heartbeat_counter']
                until(lambda: current('availability')['heartbeat_counter'] > first_counter)
                now[0] += 31
                until(lambda: current('assets/conveyor_01/state')['observation_status'] == 'stale')
                self.assertIsNone(current('assets/conveyor_01/state')['inhibit'])
                self.assertTrue(current('assets/conveyor_01/state')['online'])
                now[0] += 1
                store.submit(sample)
                until(lambda: current('assets/conveyor_01/state')['inhibit'] is True)
                port = broker.port
                broker.stop()
                until(lambda: worker.status()['status'] in ('disconnected', 'connecting'))
                now[0] += 31
                with message_lock:
                    latest.clear()
                broker = LocalBroker(port)
                broker.start()
                until(lambda: current('assets/conveyor_01/state'))
                self.assertIsNone(current('assets/conveyor_01/state')['inhibit'])
                worker.stop()
                until(lambda: current('availability') and current('availability')['status'] == 'offline')
                self.assertFalse(current('availability')['online'])
                # New subscribers receive retained latest state and offline availability.
                with message_lock:
                    latest.clear()
                subscriber.subscribe(prefix + '/#', qos=1)
                until(lambda: current('availability') and current('availability')['status'] == 'offline')
                until(lambda: current('assets/conveyor_01/state'))
                self.assertIsNone(current('assets/conveyor_01/state')['inhibit'])
            finally:
                worker.stop()
                subscriber.disconnect()
                subscriber.loop_stop()
                broker.stop()
                store.close()


@unittest.skipUnless(importlib.util.find_spec('asyncua'), 'Install requirements.txt for OPC UA checks.')
class OpcUaTests(unittest.TestCase):
    def test_readonly_nodes_numeric_value_expiry_and_stable_node_ids(self):
        from asyncua import Client, ua
        logging.getLogger('asyncua').setLevel(logging.CRITICAL)
        with tempfile.TemporaryDirectory() as directory:
            now = [time.time()]
            store = Store(Path(directory) / 'bridge.sqlite3', clock=lambda: now[0])
            store.submit(dict(asset_id='conveyor_01', source_id='manual', signal_id='presence', status='active'))
            store.submit(dict(asset_id='conveyor_01', source_id='manual', signal_id='count', kind='measurement', status='valid', value=12))
            port = free_port()
            worker = OpcUaServer(store, dict(enabled=True, port=port))
            worker.start()
            try:
                until(lambda: worker.status()['status'] in ('running', 'error'))
                self.assertEqual(worker.status()['status'], 'running')

                async def verify():
                    async with Client(f'opc.tcp://127.0.0.1:{port}/vlock/') as client:
                        index = await client.get_namespace_index(NAMESPACE)
                        def node(path):
                            return client.get_node(ua.NodeId('Bridge/' + path, index))
                        inhibit = node('Assets/conveyor_01/Inhibit')
                        numeric = node('Assets/conveyor_01/Signals/manual/count/NumericValue')
                        self.assertTrue(await node('Online').read_value())
                        self.assertEqual(await node('Status').read_value(), 'online')
                        self.assertEqual(await node('OfflineAfterSeconds').read_value(), 5)
                        self.assertIsInstance(await node('HeartbeatPulse').read_value(), bool)
                        self.assertEqual(await node('HeartbeatIntervalSeconds').read_value(), 1.)
                        first_counter = await node('HeartbeatCounter').read_value()
                        await asyncio.sleep(1.2)
                        self.assertGreater(await node('HeartbeatCounter').read_value(), first_counter)
                        self.assertIs(await inhibit.read_value(), True)
                        self.assertEqual(await numeric.read_value(), 12.)
                        with self.assertRaises(ua.UaStatusCodeError):
                            await inhibit.write_value(False)
                        self.assertIs(await inhibit.read_value(), True)
                        now[0] += 31
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            value = await inhibit.read_data_value(raise_on_bad_status=False)
                            if value.StatusCode.is_bad():
                                break
                            await asyncio.sleep(.1)
                        self.assertEqual(value.StatusCode.value, ua.StatusCodes.BadNoCommunication)
                        self.assertIsNone(value.Value.Value)
                        self.assertTrue(await node('Online').read_value())
                        self.assertFalse(await node('Assets/conveyor_01/InhibitKnown').read_value())
                        self.assertTrue((await numeric.read_data_value(raise_on_bad_status=False)).StatusCode.is_bad())
                        state = json.loads(await node('Assets/conveyor_01/StateJson').read_value())
                        self.assertIsNone(state['inhibit'])
                        self.assertEqual(state['signals'][0]['status'], 'stale')
                        now[0] += 1
                        store.submit(dict(asset_id='conveyor_01', source_id='manual', signal_id='presence', status='clear'))
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            value = await inhibit.read_data_value(raise_on_bad_status=False)
                            if value.StatusCode.is_good():
                                break
                            await asyncio.sleep(.1)
                        self.assertTrue(value.StatusCode.is_good())
                        self.assertIs(value.Value.Value, False)
                        self.assertTrue(await node('Assets/conveyor_01/InhibitKnown').read_value())
                asyncio.run(verify())
            finally:
                worker.stop()
                store.close()


if __name__ == '__main__':
    unittest.main()
