"""Explicit local OPC UA read mappings and observation output mappings."""
import asyncio
import math
import os
import re
import time
from urllib.parse import urlsplit

from .store import BridgeError, encode, identifier, utc
from .transports import Worker, asset_document


def node_id(value):
    if not isinstance(value, str) or len(value) > 1024 or not re.fullmatch(
            r'(?:(?:ns=\d+|nsu=[^;\s]+);)?(?:i=\d+|s=.+|g=[0-9a-fA-F-]{36}|b=[A-Za-z0-9+/=]+)', value):
        raise BridgeError('Use an OPC UA Node ID, for example ns=2;s=Example or nsu=urn:example;s=Example.')
    return value


def validate_client_settings(settings):
    if settings['mode'] not in ('server', 'client') or settings['security'] not in ('None', 'Basic256Sha256'):
        raise BridgeError('Choose server/client mode and None/Basic256Sha256 security.')
    try:
        url = urlsplit(settings['endpoint'])
        valid = (url.scheme == 'opc.tcp' and url.hostname in ('localhost', '127.0.0.1')
                 and url.port is not None and 1024 <= url.port <= 65535
                 and not url.username and not url.password and not url.query and not url.fragment)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise BridgeError('Use a local opc.tcp endpoint with an explicit port and no credentials.')
    if settings['mode'] == 'client' and url.port == settings['port']:
        raise BridgeError('The client endpoint must differ from the bridge server port.')
    for key in ('reads', 'writes'):
        if not isinstance(settings[key], list) or len(settings[key]) > 16:
            raise BridgeError('Use up to 16 read mappings and 16 write mappings.')
    targets = []
    for mapping in settings['reads']:
        if not isinstance(mapping, dict) or set(mapping) != {'label', 'node_id'}:
            raise BridgeError('Each read mapping needs label and node_id.')
        identifier(mapping['label'], 'read label')
        node_id(mapping['node_id'])
    if len({m['label'] for m in settings['reads']}) != len(settings['reads']):
        raise BridgeError('Read labels must be unique.')
    for mapping in settings['writes']:
        if not isinstance(mapping, dict) or mapping.get('field') not in ('state_json', 'inhibit'):
            raise BridgeError('Write field must be state_json or inhibit.')
        fields = {'asset_id', 'field', 'node_id'}
        if mapping['field'] == 'inhibit':
            fields.add('known_node_id')
        if set(mapping) != fields:
            raise BridgeError('Write mappings need asset_id, field, node_id; inhibit also needs known_node_id.')
        identifier(mapping['asset_id'], 'asset_id')
        targets.append(node_id(mapping['node_id']))
        if mapping['field'] == 'inhibit':
            targets.append(node_id(mapping['known_node_id']))
    heartbeat = settings['heartbeat_node_id']
    if heartbeat:
        targets.append(node_id(heartbeat))
    elif not isinstance(heartbeat, str) or settings['writes']:
        raise BridgeError('Write mappings require a Boolean heartbeat_node_id for the receiver watchdog.')
    if len(targets) != len(set(targets)):
        raise BridgeError('Write targets and the heartbeat must be distinct nodes.')
    if set(targets) & {m['node_id'] for m in settings['reads']}:
        raise BridgeError('Read and write mappings must use separate nodes to avoid feedback.')


def display_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


class OpcUaClient(Worker):
    def stop(self):
        self.stop_event.set()
        loop = getattr(self, '_loop', None)
        task = getattr(self, '_task', None)
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The worker already closed its loop.
        super().stop()

    def status(self):
        state = super().status()
        with self.lock:
            reads = [dict(row) for row in self.state.get('reads', [])]
        if not state['online']:
            reads = [row | {'value': None, 'available': False, 'quality': 'Unavailable'} for row in reads]
        state['reads'] = reads
        return state

    def run(self):
        try:
            asyncio.run(self.reconnect())
        except asyncio.CancelledError:
            self.report('disabled', 'OPC UA client stopped.')
        except ImportError:
            self.report('unavailable', 'Install requirements.txt to enable OPC UA.')
        except Exception:
            self.report('error', 'OPC UA client could not start. Check local client configuration.')

    async def reconnect(self):
        from asyncua import Client
        from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
        from asyncua import ua
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        while not self.stop_event.is_set():
            try:
                self.report('connecting', 'Connecting to the configured local OPC UA server.')
                client = Client(self.settings['endpoint'], timeout=2)
                client.application_uri = 'urn:vlock:bridge:client'
                if self.settings['security'] == 'Basic256Sha256':
                    paths = [os.environ.get('VLOCK_BRIDGE_OPCUA_' + name) for name in
                             ('CERTIFICATE', 'PRIVATE_KEY', 'SERVER_CERTIFICATE')]
                    if not all(paths):
                        self.report('error', 'Set OPC UA certificate, private key and trusted server certificate environment paths.')
                        return
                    await client.set_security(SecurityPolicyBasic256Sha256, paths[0], paths[1],
                                              server_certificate=paths[2], mode=ua.MessageSecurityMode.SignAndEncrypt)
                username = os.environ.get('VLOCK_BRIDGE_OPCUA_USERNAME')
                password = os.environ.get('VLOCK_BRIDGE_OPCUA_PASSWORD')
                if username:
                    client.set_user(username)
                    if password is not None:
                        client.set_password(password)
                async with client:
                    await self.connected(client)
            except Exception:
                # UA exceptions and endpoint descriptions can contain credentials.
                self.report('disconnected', 'Cannot confirm OPC UA exchange. Check endpoint, trust, credentials, Node IDs and permissions; retrying.')
            for _ in range(20):
                if self.stop_event.is_set():
                    break
                await asyncio.sleep(.1)
        self.report('disabled', 'OPC UA client stopped.')

    async def resolve(self, client, text):
        from asyncua import ua
        parsed = ua.NodeId.from_string(text)
        if getattr(parsed, 'NamespaceUri', None):
            index = await client.get_namespace_index(parsed.NamespaceUri)
            parsed = ua.NodeId(parsed.Identifier, index, parsed.NodeIdType)
        return client.get_node(parsed)

    async def connected(self, client):
        from asyncua import ua
        reads = [(mapping, await self.resolve(client, mapping['node_id'])) for mapping in self.settings['reads']]
        writes = [(mapping, await self.resolve(client, mapping['node_id']),
                   await self.resolve(client, mapping['known_node_id']) if mapping['field'] == 'inhibit' else None)
                  for mapping in self.settings['writes']]
        heartbeat = await self.resolve(client, self.settings['heartbeat_node_id']) if self.settings['heartbeat_node_id'] else None
        # Resolve aliases before comparing, including namespace-URI versus index forms.
        targets = [node.nodeid for _, node, known in writes for node in (node, known) if node is not None]
        if heartbeat is not None:
            targets.append(heartbeat.nodeid)
        if len(set(targets)) != len(targets) or set(targets) & {node.nodeid for _, node in reads}:
            raise ValueError('Overlapping resolved mappings')
        # Validate all output datatypes before making the first write.
        for mapping, node, known in writes:
            expected = ua.VariantType.String if mapping['field'] == 'state_json' else ua.VariantType.Boolean
            if await node.read_data_type_as_variant_type() != expected:
                raise ValueError('Output datatype mismatch')
            if known is not None and await known.read_data_type_as_variant_type() != ua.VariantType.Boolean:
                raise ValueError('Validity datatype mismatch')
        if heartbeat is not None and await heartbeat.read_data_type_as_variant_type() != ua.VariantType.Boolean:
            raise ValueError('Heartbeat datatype mismatch')
        while not self.stop_event.is_set():
            # A real server read confirms the session even with empty mappings.
            await client.nodes.server_state.read_value()
            rows = []
            for mapping, node in reads:
                data = await node.read_data_value(raise_on_bad_status=False)
                value = display_value(data.Value.Value) if data.Value else None
                available = data.StatusCode.is_good() and value is not None
                rows.append(dict(label=mapping['label'], node_id=mapping['node_id'],
                    value=value if available else None, available=available,
                    quality=data.StatusCode.name, source_timestamp=data.SourceTimestamp.isoformat() if data.SourceTimestamp else None,
                    received_at=utc(time.time())))
            # Readbacks are diagnostic only: never fed back into observations.
            with self.lock:
                self.state['reads'] = rows
            snapshot = self.store.snapshot()
            assets = {asset['asset_id']: asset for asset in snapshot['assets']}
            for mapping, node, known in writes:
                asset = assets.get(mapping['asset_id'])
                if known is not None:
                    # Invalid until the entire value update is acknowledged.
                    await known.write_value(False, ua.VariantType.Boolean)
                    if asset and asset['quality'] == 'good' and asset['inhibit'] is not None:
                        await node.write_value(asset['inhibit'], ua.VariantType.Boolean)
                        await known.write_value(True, ua.VariantType.Boolean)
                else:
                    payload = asset_document(snapshot, asset) if asset else dict(
                        schema_version=1, asset_id=mapping['asset_id'], inhibit=None,
                        quality='unknown', observation_status='unknown', signals=[],
                        heartbeat=snapshot['heartbeat'], session_id=snapshot['session_id'])
                    await node.write_value(encode(payload), ua.VariantType.String)
            # Advance the receiver watchdog only after all mapped operations succeed.
            if heartbeat is not None:
                await heartbeat.write_value(snapshot['heartbeat_pulse'], ua.VariantType.Boolean)
            message = ('Mapped reads and observation writes acknowledged by the server.' if reads or writes
                       else 'Server responding; no tag mappings configured.')
            self.report('connected', message, updated=True)
            await asyncio.sleep(.5)
