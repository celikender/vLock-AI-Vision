"""Small, durable observation bridge. No machine commands or reset logic."""
import json
import math
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from heartbeat import Heartbeat
from store_time import utc


class BridgeError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise BridgeError(f'{name}: use 1-64 letters, numbers, underscores or hyphens.')
    return value


def encode(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':'))


def validate(data):
    if not isinstance(data, dict):
        raise BridgeError('Send a JSON object.')
    fields = {'observation_id', 'asset_id', 'source_id', 'signal_id', 'kind', 'status',
              'reason', 'value', 'details', 'observed_at', 'ttl_seconds'}
    if data.keys() - fields:
        raise BridgeError('Unknown fields: ' + ', '.join(sorted(data.keys() - fields)))
    result = {name: identifier(data.get(name), name) for name in ('asset_id', 'source_id', 'signal_id')}
    result['observation_id'] = identifier(data.get('observation_id', str(uuid4())), 'observation_id')
    result['kind'] = data.get('kind', 'condition')
    if result['kind'] not in ('condition', 'measurement'):
        raise BridgeError('kind must be condition or measurement.')
    statuses = ('active', 'clear', 'unknown') if result['kind'] == 'condition' else ('valid', 'unknown')
    if data.get('status') not in statuses:
        raise BridgeError('status must be ' + ', '.join(statuses) + '.')
    result['status'] = data['status']
    reason = data.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 240:
        raise BridgeError('reason must be text up to 240 characters.')
    result['reason'] = reason.strip()
    ttl = data.get('ttl_seconds', 30)
    if isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not 1 <= ttl <= 3600 or not math.isfinite(ttl):
        raise BridgeError('ttl_seconds must be a number from 1 to 3600.')
    result['ttl_seconds'] = ttl
    result['value'] = data.get('value')
    if result['kind'] == 'measurement' and result['status'] == 'valid' and result['value'] is None:
        raise BridgeError('A valid measurement requires value.')
    result['details'] = data.get('details', {})
    if not isinstance(result['details'], dict):
        raise BridgeError('details must be a JSON object.')
    result['observed_at'] = data.get('observed_at')
    if result['observed_at'] is not None:
        try:
            stamp = datetime.fromisoformat(result['observed_at'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError()
            result['observed_at'] = utc(stamp.timestamp())
        except (AttributeError, ValueError, TypeError, OverflowError, OSError):
            raise BridgeError('observed_at must be an ISO 8601 timestamp with timezone.') from None
    try:
        if len(encode(result).encode()) > 65536:
            raise BridgeError('Observation exceeds 64 KiB.')
    except (ValueError, TypeError, RecursionError):
        raise BridgeError('Use finite, JSON-compatible values.') from None
    return result


class Store:
    def __init__(self, path, clock=time.time, heartbeat=None, heartbeat_interval_seconds=1, history_limit=1000):
        if isinstance(history_limit, bool) or not isinstance(history_limit, int) or not 5 <= history_limit <= 100000:
            raise ValueError('History limit must be from 5 to 100000 events.')
        self.clock = clock
        self.history_limit = history_limit
        self.lock = threading.RLock()
        self.session_id = str(uuid4())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, observed_seconds REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS signals (
                asset_id TEXT NOT NULL, source_id TEXT NOT NULL, signal_id TEXT NOT NULL,
                kind TEXT NOT NULL, observation_id TEXT NOT NULL REFERENCES observations,
                unavailable TEXT,
                PRIMARY KEY (asset_id, source_id, signal_id));
            CREATE TABLE IF NOT EXISTS events (
                revision INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                created_at TEXT NOT NULL, asset_id TEXT, payload TEXT NOT NULL,
                observation_id TEXT);
        ''')
        with self.db:
            if 'observation_id' not in {row['name'] for row in self.db.execute('PRAGMA table_info(events)')}:
                self.db.execute('ALTER TABLE events ADD COLUMN observation_id TEXT')
                for row in self.db.execute('SELECT revision,payload FROM events').fetchall():
                    observation_id = json.loads(row['payload']).get('observation_id')
                    self.db.execute('UPDATE events SET observation_id=? WHERE revision=?', (observation_id, row['revision']))
            self.db.execute('CREATE INDEX IF NOT EXISTS events_observation_id ON events(observation_id)')
        # Persist history, but never restore an old Clear as a fresh observation.
        with self.lock, self.db:
            for row in self.db.execute('SELECT * FROM signals WHERE unavailable IS NULL').fetchall():
                self.db.execute('UPDATE signals SET unavailable=? WHERE asset_id=? AND source_id=? AND signal_id=?',
                                ('restart', row['asset_id'], row['source_id'], row['signal_id']))
                self._event('unavailable', row['asset_id'], dict(source_id=row['source_id'],
                            signal_id=row['signal_id'], reason='restart'))
            self._prune_history()
        self.heartbeat = heartbeat or Heartbeat(heartbeat_interval_seconds)

    def close(self):
        self.heartbeat.close()
        with self.lock:
            self.db.close()

    def _event(self, kind, asset_id, payload):
        self.db.execute('INSERT INTO events(event_type,created_at,asset_id,payload,observation_id) VALUES(?,?,?,?,?)',
                        (kind, utc(self.clock()), asset_id, encode(payload), payload.get('observation_id')))
        self._prune_history()

    def _prune_history(self):
        self.db.execute('''DELETE FROM events WHERE revision < (
            SELECT revision FROM events ORDER BY revision DESC LIMIT 1 OFFSET ?)''', (self.history_limit - 1,))
        self.db.execute('''DELETE FROM observations WHERE observation_id NOT IN (
            SELECT observation_id FROM signals) AND observation_id NOT IN (
            SELECT observation_id FROM events WHERE observation_id IS NOT NULL)''')

    def history_info(self):
        with self.lock:
            row = self.db.execute('SELECT COUNT(*) AS count, MIN(revision) AS oldest FROM events').fetchone()
            return dict(retention_limit=self.history_limit, stored_count=row['count'], oldest_revision=row['oldest'])

    def _expire(self):
        rows = self.db.execute('''SELECT s.*, o.payload, o.observed_seconds FROM signals s
                                 JOIN observations o USING(observation_id) WHERE s.unavailable IS NULL''').fetchall()
        for row in rows:
            sample = json.loads(row['payload'])
            if self.clock() >= row['observed_seconds'] + sample['ttl_seconds']:
                self.db.execute('UPDATE signals SET unavailable=? WHERE asset_id=? AND source_id=? AND signal_id=?',
                                ('stale', row['asset_id'], row['source_id'], row['signal_id']))
                self._event('expired', row['asset_id'], dict(source_id=row['source_id'],
                            signal_id=row['signal_id'], observation_id=row['observation_id']))

    def submit(self, data):
        sample = validate(data)
        fingerprint = encode(sample)
        key = tuple(sample[name] for name in ('asset_id', 'source_id', 'signal_id'))
        with self.lock, self.db:
            self._expire()
            previous_id = self.db.execute('SELECT * FROM observations WHERE observation_id=?',
                                          (sample['observation_id'],)).fetchone()
            if previous_id:
                if previous_id['fingerprint'] != fingerprint:
                    raise BridgeError('observation_id already exists with different content.', 409)
                return {'duplicate': True, 'observation': json.loads(previous_id['payload'])}
            now = self.clock()
            observed = now if sample['observed_at'] is None else datetime.fromisoformat(
                sample['observed_at'].replace('Z', '+00:00')).timestamp()
            if observed > now + 1 or now >= observed + sample['ttl_seconds']:
                raise BridgeError('Observation is expired or its timestamp is in the future.', 422)
            previous = self.db.execute('''SELECT s.kind, o.observed_seconds FROM signals s
                                         JOIN observations o USING(observation_id)
                                         WHERE asset_id=? AND source_id=? AND signal_id=?''', key).fetchone()
            if previous:
                if previous['kind'] != sample['kind']:
                    raise BridgeError('Signal kind cannot change. Use a different signal_id.', 409)
                if observed <= previous['observed_seconds']:
                    raise BridgeError('Observation is repeated or out of order for this signal.', 409)
            sample['observed_at'] = utc(observed)
            sample['received_at'] = utc(now)
            sample['expires_at'] = utc(observed + sample['ttl_seconds'])
            self.db.execute('INSERT INTO observations VALUES(?,?,?,?)',
                            (sample['observation_id'], fingerprint, encode(sample), observed))
            self.db.execute('''INSERT INTO signals VALUES(?,?,?,?,?,NULL)
                ON CONFLICT(asset_id,source_id,signal_id) DO UPDATE SET
                observation_id=excluded.observation_id, unavailable=NULL''',
                (*key, sample['kind'], sample['observation_id']))
            self._event('observation', sample['asset_id'], sample)
            return {'duplicate': False, 'observation': sample}

    def snapshot(self):
        with self.lock, self.db:
            self._expire()
            assets = {}
            rows = self.db.execute('''SELECT s.unavailable, o.payload FROM signals s
                JOIN observations o USING(observation_id) ORDER BY s.asset_id,s.source_id,s.signal_id''')
            for row in rows:
                sample = json.loads(row['payload'])
                sample['status'] = ('stale' if row['unavailable'] == 'stale' else 'unknown') if row['unavailable'] else sample['status']
                sample['unavailable_reason'] = row['unavailable']
                assets.setdefault(sample['asset_id'], []).append(sample)
            output = []
            for asset_id, signals in assets.items():
                conditions = [s for s in signals if s['kind'] == 'condition']
                active = [s for s in conditions if s['status'] == 'active']
                unavailable = [s for s in conditions if s['status'] in ('unknown', 'stale')]
                inhibit = True if active else None if unavailable or not conditions else False
                status = 'active' if active else 'stale' if unavailable and all(s['status'] == 'stale' for s in unavailable) else 'unknown' if inhibit is None else 'clear'
                reasons = [dict(source_id=s['source_id'], signal_id=s['signal_id'], status=s['status'],
                                reason=s['unavailable_reason'] or s['reason'] or s['status']) for s in active + unavailable]
                output.append(dict(asset_id=asset_id, inhibit=inhibit, observation_status=status,
                    quality='uncertain' if active and unavailable else 'unknown' if inhibit is None else 'good',
                    reasons=reasons, signals=signals))
            revision = self.db.execute('SELECT COALESCE(MAX(revision),0) FROM events').fetchone()[0]
            return dict(schema_version=1, session_id=self.session_id, **self.heartbeat.snapshot(),
                        revision=revision, assets=output)

    def events(self, after=None, limit=50):
        with self.lock, self.db:
            self._expire()
            # Without a cursor, show recent history. With a cursor, replay in order.
            direction = 'ASC' if after is not None else 'DESC'
            rows = self.db.execute(f'SELECT * FROM events WHERE revision>? ORDER BY revision {direction} LIMIT ?',
                                   (after if after is not None else 0, limit)).fetchall()
            result = [dict(revision=r['revision'], event_type=r['event_type'], created_at=r['created_at'],
                           asset_id=r['asset_id'], data=json.loads(r['payload'])) for r in rows]
            if after is None:
                result.reverse()
            return result
