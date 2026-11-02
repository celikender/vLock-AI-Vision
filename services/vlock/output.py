"""Local durable observation publication. No protocol or machine command side effects."""
import copy
import time
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .store import BridgeError


class ObservationOutput:
    def __init__(self, store, zone):
        self.store=store
        self.zone=copy.deepcopy(zone)
        self.status=dict(state='idle',message='No observation recorded.',last_sent_at=None)

    def send(self, config, state, reason, captured_at=None, count=None, details=None):
        age=time.monotonic()-captured_at if captured_at is not None else None
        ttl=config.get('validity_seconds',10)
        fresh=age is not None and 0<=age<ttl
        observed=datetime.fromtimestamp(time.time()-age if fresh else time.time(),timezone.utc).isoformat()
        output_type=self.zone['outputType']
        kind='condition' if output_type=='condition' else 'measurement'
        payload=dict(observation_id=str(uuid4()),asset_id=self.zone['id'],source_id='vision',
            signal_id=self.zone['output'],kind=kind,observed_at=observed,ttl_seconds=ttl,
            reason=str(reason)[:240],details=dict(target=config['sam_prompt'],zone=self.zone['name'],
                output_type=output_type,**(details or {})))
        if kind=='condition':
            payload['status']={'Warning':'active','Normal':'clear'}.get(state,'unknown') if fresh else 'unknown'
        elif output_type=='count':
            payload.update(status='valid' if fresh and count is not None else 'unknown',value=count if fresh else None)
        else:
            known=fresh and state in ('Warning','Normal')
            payload.update(status='valid' if known else 'unknown',value={'state':state} if known else None)
        try:
            self.store.submit(payload)
            self.status=dict(state='recorded',message='Observation recorded by the local output service.',
                last_sent_at=datetime.now(timezone.utc).isoformat())
        except (BridgeError,OSError,ValueError,sqlite3.Error):
            self.status=dict(state='error',message='Local observation was not confirmed; previous samples expire.',
                last_sent_at=self.status['last_sent_at'])
