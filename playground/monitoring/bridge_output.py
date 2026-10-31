"""Bounded, loopback-only publication of monitoring observations. No machine commands."""
import http.client
import json
import time
from datetime import datetime, timezone
from uuid import uuid4


class BridgeOutput:
    def __init__(self, port=5055):
        self.port = port
        self.status = {'state': 'idle', 'message': 'No observations sent.', 'last_sent_at': None}

    def send(self, config, state, reason, captured_at=None, count=None, details=None):
        settings = config.get('bridge', {})
        if not settings.get('enabled'):
            return
        age = time.monotonic() - captured_at if captured_at is not None else 0
        fresh = captured_at is not None and 0 <= age < 10
        observed_at = datetime.fromtimestamp(time.time() - age if fresh else time.time(), timezone.utc).isoformat()
        common = dict(asset_id=settings['asset_id'], source_id='sam', observed_at=observed_at,
                      ttl_seconds=10, reason=reason[:240],
                      details=dict(prompt=config['sam_prompt'], zone=config['zone']['name'], **(details or {})))
        observations = [
            dict(signal_id='people_count', kind='measurement', status='valid' if fresh and count is not None else 'unknown',
                 value=count if fresh else None),
            dict(signal_id='zone_condition', kind='condition',
                 status={'Warning': 'active', 'Normal': 'clear'}.get(state, 'unknown') if fresh else 'unknown')]
        try:
            for observation in observations:
                connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=0.5)
                try:
                    payload = dict(common, **observation, observation_id=str(uuid4()))
                    connection.request('POST', '/api/v1/observations', json.dumps(payload, allow_nan=False),
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    response.read(65537)
                    if response.status not in (200, 201):
                        raise OSError('Bridge rejected observation.')
                finally:
                    connection.close()
            self.status = dict(state='sent', message='Bridge accepted the latest observations.',
                               last_sent_at=datetime.now(timezone.utc).isoformat())
        except (OSError, http.client.HTTPException, ValueError):
            self.status = dict(state='error', message='Publication not confirmed. Check bridge on localhost:5055; old observations expire.',
                               last_sent_at=self.status['last_sent_at'])
