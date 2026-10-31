"""Optional local MQTT publisher and read-only OPC UA server over one Store."""
import asyncio
import copy
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from store import BridgeError, encode, utc

NAMESPACE = 'urn:vlock:bridge:v1'
DEFAULTS = {
    'mqtt': {'enabled': False, 'host': '127.0.0.1', 'port': 1883, 'topic_prefix': 'vlock/v1'},
    'opcua': {'enabled': False, 'port': 4845},
}


def configuration(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULTS):
        raise BridgeError('Supply mqtt and opcua settings.')
    for name, defaults in DEFAULTS.items():
        if not isinstance(data[name], dict) or set(data[name]) != set(defaults):
            raise BridgeError(f'Check {name} settings; unknown or missing fields.')
        if not isinstance(data[name]['enabled'], bool):
            raise BridgeError(f'{name}.enabled must be true or false.')
        port = data[name]['port']
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise BridgeError(f'{name}.port must be an integer from 1024 to 65535.')
    if data['mqtt']['host'] not in ('127.0.0.1', 'localhost'):
        raise BridgeError('This experiment accepts a local MQTT broker only: localhost or 127.0.0.1.')
    prefix = data['mqtt']['topic_prefix']
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', prefix) or len(prefix) > 120:
        raise BridgeError('Use a topic prefix of letters, digits, hyphens, underscores and single slashes (up to 120 characters).')
    if data['mqtt']['port'] == data['opcua']['port']:
        raise BridgeError('MQTT and OPC UA must use different ports.')
    return copy.deepcopy(data)


def asset_document(snapshot, asset):
    return {key: value for key, value in snapshot.items() if key != 'assets'} | asset


class Worker:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.state = {'status': 'starting', 'message': 'Starting adapter.', 'last_update': None}
        self.last_progress = None
        self.heartbeat_counter = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def report(self, status, message, updated=False):
        with self.lock:
            self.state.update(status=status, message=message)
            if updated:
                self.state['last_update'] = utc(time.time())
                self.last_progress = time.monotonic()
                self.heartbeat_counter += 1

    def status(self):
        with self.lock:
            state = dict(self.state)
            online = state['status'] in ('connected', 'running') and self.last_progress is not None and time.monotonic() - self.last_progress < 5
            if state['status'] in ('connected', 'running') and not online:
                state.update(status='stale', message='Adapter heartbeat is overdue.')
            return dict(state, online=online, heartbeat_counter=self.heartbeat_counter, offline_after_seconds=5)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=8)
        if self.thread.is_alive():
            raise BridgeError('Adapter is still stopping. Wait before applying settings again.', 503)


class MqttPublisher(Worker):
    """A new client on each reconnect drops its old outgoing queue."""
    def run(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.report('unavailable', 'Install playground/vlock_bridge/requirements.txt to enable MQTT.')
            return
        prefix = self.settings['topic_prefix']
        availability = prefix + '/availability'
        offline = encode(dict(schema_version=1, status='offline', online=False,
            session_id=self.store.session_id, heartbeat=None, heartbeat_counter=None,
            heartbeat_pulse=None, heartbeat_interval_seconds=self.store.heartbeat.interval,
            offline_after_seconds=self.store.heartbeat.timeout))
        while not self.stop_event.is_set():
            client = None
            try:
                self.report('connecting', 'Connecting to the local broker.')
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id='vlock-' + self.store.session_id[:12], clean_session=True,
                    protocol=mqtt.MQTTv311, reconnect_on_failure=False)
                client.connect_timeout = 2
                client.max_queued_messages_set(128)
                client.max_inflight_messages_set(20)
                client.will_set(availability, offline, qos=1, retain=True)
                username = os.environ.get('VLOCK_BRIDGE_MQTT_USERNAME')
                password = os.environ.get('VLOCK_BRIDGE_MQTT_PASSWORD')
                if username:
                    client.username_pw_set(username, password)
                client.connect(self.settings['host'], self.settings['port'], keepalive=10)
                client.loop_start()
                deadline = time.monotonic() + 4
                while not client.is_connected() and time.monotonic() < deadline and not self.stop_event.wait(.05):
                    pass
                if not client.is_connected():
                    raise OSError('Broker handshake unavailable')
                while not self.stop_event.is_set() and client.is_connected():
                    snapshot = self.store.snapshot()
                    messages = [(prefix + '/state', snapshot)]
                    messages.extend((prefix + '/assets/' + a['asset_id'] + '/state', asset_document(snapshot, a))
                                    for a in snapshot['assets'])
                    messages.append((availability, dict(schema_version=1,
                        status='online' if snapshot['online'] else 'offline', session_id=snapshot['session_id'],
                        **{key: snapshot[key] for key in ('heartbeat', 'online', 'heartbeat_counter',
                            'heartbeat_pulse', 'heartbeat_interval_seconds', 'offline_after_seconds')})))
                    pending = [client.publish(topic, encode(payload), qos=1, retain=True) for topic, payload in messages]
                    deadline = time.monotonic() + 3
                    while any(not info.is_published() for info in pending):
                        if not client.is_connected() or time.monotonic() >= deadline:
                            raise OSError('Publication was not acknowledged')
                        if self.stop_event.wait(.05):
                            break
                    if not self.stop_event.is_set():
                        self.report('connected', 'Latest state acknowledged by the broker.', updated=True)
                    self.stop_event.wait(1)
                if not self.stop_event.is_set():
                    raise OSError('Broker disconnected')
            except Exception:
                # Never display transport exceptions: some contain connection credentials.
                self.report('disconnected', 'Cannot confirm MQTT delivery. Check broker, port and credentials; retrying.')
            finally:
                if client:
                    try:
                        if client.is_connected():
                            result = client.publish(availability, offline, qos=1, retain=True)
                            result.wait_for_publish(timeout=1)
                        client.disconnect()
                        client.loop_stop()
                    except Exception:
                        pass
            self.stop_event.wait(2)
        self.report('disabled', 'MQTT stopped.')


class OpcUaServer(Worker):
    def run(self):
        try:
            asyncio.run(self.serve())
        except ImportError:
            self.report('unavailable', 'Install playground/vlock_bridge/requirements.txt to enable OPC UA.')
        except Exception:
            self.report('error', 'OPC UA could not run. Check its port and adapter dependencies, then apply settings again.')

    async def serve(self):
        from asyncua import Server, ua
        from asyncua.crypto.permission_rules import User, UserRole

        class ReaderUsers:
            def get_user(self, iserver, username=None, password=None, certificate=None):
                # No special username can become an administrator over this local endpoint.
                return User(role=UserRole.User)

        server = Server(user_manager=ReaderUsers())
        await server.init()
        server.set_endpoint(f'opc.tcp://127.0.0.1:{self.settings["port"]}/vlock/')
        server.set_server_name('vLock Bridge')
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace = await server.register_namespace(NAMESPACE)
        self.nodes = {}
        self.objects = {}
        self.ua = ua
        self.namespace = namespace
        root = await server.nodes.objects.add_object(ua.NodeId('Bridge', namespace), 'vLock')
        self.objects['Bridge'] = root

        async def variable(parent, path, name, value, variant, status=None, observed_at=None):
            if path not in self.nodes:
                self.nodes[path] = await parent.add_variable(ua.NodeId(path, namespace), name, value, variant)
                await self.nodes[path].set_read_only()
            await self.nodes[path].write_value(ua.DataValue(ua.Variant(value, variant),
                StatusCode=ua.StatusCode(status or ua.StatusCodes.Good),
                SourceTimestamp=datetime.fromisoformat(observed_at.replace('Z', '+00:00')) if observed_at else datetime.now(timezone.utc),
                ServerTimestamp=datetime.now(timezone.utc)))

        self.variable = variable
        await variable(root, 'Bridge/Heartbeat', 'Heartbeat', '', ua.VariantType.String)
        await variable(root, 'Bridge/SessionId', 'SessionId', self.store.session_id, ua.VariantType.String)
        await variable(root, 'Bridge/Revision', 'Revision', 0, ua.VariantType.Int64)
        await self.update(self.store.snapshot())
        async with server:
            while not self.stop_event.is_set():
                await self.update(self.store.snapshot())
                self.report('running', 'Read-only local endpoint is publishing state.', updated=True)
                await asyncio.sleep(.5)
            await variable(root, 'Bridge/Online', 'Online', False, ua.VariantType.Boolean)
            await variable(root, 'Bridge/Status', 'Status', 'offline', ua.VariantType.String)
        self.report('disabled', 'OPC UA stopped.')

    async def object(self, parent, path, name):
        if path not in self.objects:
            self.objects[path] = await parent.add_object(self.ua.NodeId(path, self.namespace), name)
        return self.objects[path]

    async def update(self, snapshot):
        ua = self.ua
        root = self.objects['Bridge']
        for asset in snapshot['assets']:
            path = 'Bridge/Assets/' + asset['asset_id']
            folder = await self.object(root, path, asset['asset_id'])
            status = (ua.StatusCodes.BadNoCommunication if asset['observation_status'] == 'stale'
                      else ua.StatusCodes.BadWaitingForInitialData) if asset['inhibit'] is None else (
                      ua.StatusCodes.UncertainDataSubNormal if asset['quality'] == 'uncertain' else ua.StatusCodes.Good)
            # The node keeps Boolean datatype. Bad status makes the UA library
            # publish a null DataValue, plus InhibitKnown=False; never a good Clear.
            await self.variable(folder, path + '/Inhibit', 'Inhibit', asset['inhibit'] is not False, ua.VariantType.Boolean, status)
            await self.variable(folder, path + '/InhibitKnown', 'InhibitKnown', asset['inhibit'] is not None, ua.VariantType.Boolean)
            for name, value in [('ObservationStatus', asset['observation_status']), ('Quality', asset['quality']),
                                ('ReasonsJson', encode(asset['reasons'])), ('StateJson', encode(asset_document(snapshot, asset)))]:
                await self.variable(folder, path + '/' + name, name, value, ua.VariantType.String)
            for signal in asset['signals']:
                signal_path = path + '/Signals/' + signal['source_id'] + '/' + signal['signal_id']
                node = await self.object(folder, signal_path, signal['source_id'] + ' / ' + signal['signal_id'])
                sample_status = ua.StatusCodes.Good if signal['status'] in ('active', 'clear', 'valid') else (
                    ua.StatusCodes.BadNoCommunication if signal['status'] == 'stale' else ua.StatusCodes.BadWaitingForInitialData)
                for name, value in [('Status', signal['status']), ('Kind', signal['kind']),
                                    ('ObservedAt', signal['observed_at']), ('ExpiresAt', signal['expires_at'])]:
                    await self.variable(node, signal_path + '/' + name, name, value, ua.VariantType.String)
                await self.variable(node, signal_path + '/ValueJson', 'ValueJson', encode(signal['value']),
                                    ua.VariantType.String, sample_status, signal['observed_at'])
                if signal['kind'] == 'condition':
                    await self.variable(node, signal_path + '/Active', 'Active', signal['status'] != 'clear',
                                        ua.VariantType.Boolean, sample_status, signal['observed_at'])
                else:
                    try:
                        numeric = float(signal['value']) if isinstance(signal['value'], (int, float)) and not isinstance(signal['value'], bool) else math.nan
                    except OverflowError:
                        numeric = math.nan
                    await self.variable(node, signal_path + '/NumericValue', 'NumericValue', numeric if math.isfinite(numeric) else 0.,
                        ua.VariantType.Double, sample_status if math.isfinite(numeric) else ua.StatusCodes.BadTypeMismatch, signal['observed_at'])
        await self.variable(root, 'Bridge/Heartbeat', 'Heartbeat', snapshot['heartbeat'], ua.VariantType.String)
        await self.variable(root, 'Bridge/Online', 'Online', snapshot['online'], ua.VariantType.Boolean)
        await self.variable(root, 'Bridge/Status', 'Status', 'online' if snapshot['online'] else 'offline', ua.VariantType.String)
        await self.variable(root, 'Bridge/HeartbeatCounter', 'HeartbeatCounter', snapshot['heartbeat_counter'], ua.VariantType.Int64)
        await self.variable(root, 'Bridge/HeartbeatPulse', 'HeartbeatPulse', snapshot['heartbeat_pulse'], ua.VariantType.Boolean)
        await self.variable(root, 'Bridge/HeartbeatIntervalSeconds', 'HeartbeatIntervalSeconds', snapshot['heartbeat_interval_seconds'], ua.VariantType.Double)
        await self.variable(root, 'Bridge/OfflineAfterSeconds', 'OfflineAfterSeconds', snapshot['offline_after_seconds'], ua.VariantType.Double)
        await self.variable(root, 'Bridge/Revision', 'Revision', snapshot['revision'], ua.VariantType.Int64)


class Integrations:
    def __init__(self, store, path):
        self.store = store
        self.path = Path(path)
        self.lock = threading.RLock()
        self.settings = copy.deepcopy(DEFAULTS)
        self.workers = {}
        self.settings_error = None
        if self.path.exists():
            try:
                self.settings = configuration(json.loads(self.path.read_text(encoding='utf-8')))
            except (ValueError, OSError):
                self.settings_error = 'Saved adapter settings are invalid. Review and apply to replace them.'
        self._start()

    def _start(self):
        for name, factory in [('mqtt', MqttPublisher), ('opcua', OpcUaServer)]:
            if self.settings[name]['enabled'] and name not in self.workers:
                worker = factory(self.store, self.settings[name])
                self.workers[name] = worker
                worker.start()

    def status(self):
        with self.lock:
            return dict(schema_version=1, settings=copy.deepcopy(self.settings), settings_error=self.settings_error,
                credentials_configured=bool(os.environ.get('VLOCK_BRIDGE_MQTT_USERNAME')),
                adapters={name: worker.status() if (worker := self.workers.get(name)) else
                    dict(status='disabled', message='Adapter is disabled.', last_update=None,
                         online=False, heartbeat_counter=0, offline_after_seconds=5) for name in DEFAULTS})

    def apply(self, data):
        settings = configuration(data)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(encode(settings), encoding='utf-8')
            temporary.replace(self.path)
            for name in DEFAULTS:
                if name in self.workers and (settings[name] != self.settings[name]
                        or self.workers[name].status()['status'] in ('error', 'unavailable')):
                    self.workers[name].stop()
                    del self.workers[name]
            self.settings = settings
            self.settings_error = None
            self._start()
            return self.status()

    def close(self):
        with self.lock:
            for worker in self.workers.values():
                worker.stop()
            self.workers.clear()
