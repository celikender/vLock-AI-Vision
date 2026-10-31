# vLock Bridge - first integration experiment

A standalone, deliberately small observation-to-automation bridge. Manual inputs
stand in for future SAM 3.1 observations. All implementation stays in this
playground; the main application, model runtime and SCADA project are unchanged.

```text
Manual form / observation JSON -> validation + SQLite -> versioned JSON API
                                                              |
                                                   external SCADA / PLC
```

## Scope and ownership

Implemented: local UI, condition and measurement inputs, asset/source/signal
identities, aggregated inhibit, freshness, persistent observation/event history,
duplicate handling, timestamp ordering and a read/write HTTP API. Optional HTTPS
uses a supplied PEM certificate/key pair. The optional MQTT publisher and read-only
OPC UA server expose that same state. The base HTTP/UI needs no extra packages;
adapter dependencies are listed in this folder's requirements.txt.

SCADA / PLC owns machine actions, interlocks, permissives, latches, acknowledgements
and resets. This bridge sends no machine command. There is no worker-lock or
machine-reset implementation here. A consumer must handle missing communication
using its own watchdog and configured fallback.

Planned: live SAM normalization; rule configuration; prompt-guided setup; remote
authentication, encrypted adapter endpoints and deployment. No running Gateway
integration, model connection, or industrial validation is claimed.

## Run

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe playground/vlock_bridge/server.py
```

Open <http://localhost:5055>. The existing camera application can keep running on
5051. Stop this bridge with Ctrl+C. To use another port, add `--port 5056`.
Python 3.12 is the project runtime; the base HTTP/UI uses only the standard library.

To use MQTT and/or OPC UA, first install the optional adapter dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r playground/vlock_bridge/requirements.txt
```

Restart the bridge after installation. In **Integration**, enable the desired
adapter and click **Apply integration settings**. The HTTP API continues working
if an adapter cannot connect. Connection status confirms delivery/startup separately
from saving settings. Settings survive restart in ignored `transports.json` beside
the database. `--settings` chooses a different local settings file.

The database is created under ignored `playground/data/vlock_bridge/bridge.sqlite3`.
Use `--db playground/data/vlock_bridge/another.sqlite3` for a separate experiment.
Only one server process should own a database file. Do not share SQLite files over
a network filesystem. No existing `.env` is read or changed.

The server intentionally binds to `127.0.0.1`. HTTP/OPC UA clients, UI, and MQTT
broker must run on this PC in this version. It has no LAN listener. No CORS is enabled;
browser requests must use the same origin. Non-browser local clients may omit
Origin. Unknown Host headers and cross-site browser requests are rejected.

For local HTTPS, supply an existing certificate trusted by the client, valid for
the host used, plus its PEM private key:

```powershell
.\.venv\Scripts\python.exe playground/vlock_bridge/server.py --certfile playground/data/vlock_bridge/localhost-cert.pem --keyfile playground/data/vlock_bridge/localhost-key.pem
```

Then open <https://localhost:5055>. Certificate generation/trust installation is
not part of this experiment; do not disable client certificate verification.

## Try the first workflow

1. Keep Asset ID `conveyor_01`, Source ID `manual`, Signal ID `person_in_zone`.
2. Click **Publish active**. The output becomes `inhibit: true`.
3. Click **Publish clear**. It becomes `false` while the observation is fresh.
4. Click **Unknown**. It becomes `null`, with unknown quality.
5. Publish again with validity of two seconds. Wait: the signal becomes Stale,
   inhibit becomes null, and an expiry event appears. The page does not refresh
   the input automatically; only explicit submissions renew observations.
6. Publish an active condition from another Source ID, then clear `manual`.
   The other source's condition remains active.
7. For general data, select **Measurement / data**. The form switches to its
   separate Signal ID (initially `people_count`); each type remembers its own ID
   while the page remains open. Enter `12` or `{"count":12}` and click **Publish value**.
   Measurements do not contribute to inhibit. A measurement-only asset has no
   established inhibit state (`null`). A stream cannot change kind. The form
   identifies an existing signal's type and flags a conflict before submission;
   the API still enforces the same restriction for every client.
8. Stop/restart the server. History remains; existing signals require fresh input.

All form submissions are simulated. A source label is supplied by the local
caller, not verified model provenance. Do not label these as live perception.

## API contract v1

All JSON responses include `schema_version: 1`. Responses are not cached.
Request bodies are limited to 64 KiB. Unknown top-level fields are rejected.

| Method and path | Result |
| --- | --- |
| `POST /api/v1/observations` | Record a validated observation; 201 new, 200 exact duplicate |
| `GET /api/v1/assets` | Current signals and aggregate outputs for all observed assets |
| `GET /api/v1/assets/{asset_id}` | One asset output plus current revision/heartbeat |
| `GET /api/v1/events?limit=50` | Most recent events in ascending revision order |
| `GET /api/v1/events?after=42&limit=50` | Events after revision 42, oldest first |
| `GET /api/v1/health` | Bridge heartbeat, session ID, revision and storage availability |
| `GET /api/v1/integrations` | Saved adapter settings and actual adapter status |
| `POST /api/v1/integrations` | Validate/save settings and start/stop changed adapters |

No asset registration is required; its first observation creates its streams.
A stream is `(asset_id, source_id, signal_id)`. IDs use 1-64 letters, digits,
underscores or hyphens, starting with a letter or digit. The bridge does not
infer detection logic or translate arbitrary raw model output.

Example condition input:

```json
{
  "observation_id": "manual-001",
  "asset_id": "conveyor_01",
  "source_id": "manual",
  "signal_id": "person_in_zone",
  "kind": "condition",
  "status": "active",
  "reason": "Simulated person in the monitored zone",
  "ttl_seconds": 30,
  "details": {"count": 1}
}
```

`kind` defaults to `condition`: status is `active`, `clear` or `unknown`.
For `measurement`, status is `valid` or `unknown`; valid measurements require a
non-null JSON `value`. `details` is an optional JSON object for normalized detection
metadata, e.g. camera/rule IDs, counts, session/object IDs, boxes or scores.
No geometry or detection score is evaluated by this bridge.

`observed_at` is optional, with an ISO 8601 timezone-bearing timestamp; if omitted,
receipt time is used. Old imported detections should supply their actual observation
time. Validity is measured from observation time, never from the last UI poll.
`ttl_seconds` defaults to 30 and accepts 1-3600. Timestamps over one second into
the future, already-expired inputs and non-increasing stream timestamps are rejected.
All numeric values must be finite. `reason` accepts up to 240 characters.

If `observation_id` is omitted, the server creates one. Supply a stable ID when
retrying: while the original observation is retained, the same ID/content is
acknowledged without writing another observation or renewing freshness, even
after expiry. Reusing a retained ID with different content
returns 409. An old duplicate never replaces a newer stream value. Keep the
original body when retrying; an omitted timestamp is part of that original request.

PowerShell example (local client, no browser Origin required):

```powershell
$observation = @{
    observation_id = [guid]::NewGuid().ToString()
    asset_id = 'conveyor_01'
    source_id = 'manual'
    signal_id = 'person_in_zone'
    kind = 'condition'
    status = 'active'
    reason = 'Simulated person in zone'
    ttl_seconds = 30
} | ConvertTo-Json
Invoke-RestMethod http://localhost:5055/api/v1/observations -Method Post -ContentType application/json -Body $observation
Invoke-RestMethod http://localhost:5055/api/v1/assets/conveyor_01
```

### Inhibit and freshness

- Any fresh active condition produces `inhibit: true`.
- All condition streams must be fresh and clear to produce `false`.
- With no active condition, any Unknown/Stale condition produces `null`.
- No condition streams also produces `null`; measurements cannot establish Clear.
- A known active plus an unknown condition remains true, with `quality: uncertain`.
- Otherwise quality is `good` for established active/clear, or `unknown` for null.

These are current observations, not latched control decisions. Nothing resets
SCADA, resumes equipment, or overrides another interlock. The aggregate includes
every condition stream ever created for the asset; v1 has no stream delete or
disable function. Use a fresh observation to recover a stale stream, or a separate
database for a clean experiment.

The response includes per-signal observation/receipt/expiry times, current status,
reason, original data, and aggregate reasons. An expired value remains available
as last-known data with Stale status; do not treat it as current. Expiry transitions
are evaluated and recorded when the API is read or written (the UI polls each
second). No timer is required to make an expired sample invalid at the next read.

On process restart, existing streams become Unknown with `unavailable_reason:
restart`. History remains. Exact duplicate retries do not revalidate them; a new
fresh observation is required. `session_id` changes on restart. `revision` is the
durable global event sequence, not an individual signal's timestamp.

Consumers must use quality/status and expiry with their own communication timeout.
A responsive bridge heartbeat does not renew observation validity. The timeout
and machine response belong to the consuming automation system.

Errors: 400 malformed/invalid input; 403 wrong host/origin; 404 absent asset/route;
409 conflicting ID, stream kind, or ordering; 413 oversized input; 415 wrong content
type; 422 expired/future input; 503 storage/unconfirmed request. The client should
not automatically retry a write with a new ID after an uncertain outcome.

## Online / Offline and heartbeat

The UI shows **Bridge: Online/Offline**, last-heartbeat age, and separate
MQTT / OPC UA badges. Bridge health is independent of observation freshness: a
running bridge can be Online while every observation is Stale. Disabled adapters
show Disabled rather than claiming a live connection.

Every HTTP snapshot and `/api/v1/health` includes:

```json
{
  "online": true,
  "heartbeat_counter": 42,
  "heartbeat_pulse": true,
  "heartbeat_interval_seconds": 1,
  "offline_after_seconds": 5
}
```

These accompany `session_id` and the existing UTC `heartbeat` timestamp. A periodic
background task toggles `heartbeat_pulse` True/False and increments the diagnostic
counter, even when no API client is reading and no observation arrives. Reading
the API never creates a beat or calculates a new beat from uptime. Heartbeats do
not create event-history records. A new process has a new session ID and restarts
the counter. The numeric count is optional diagnostic data, hidden from the UI.

The default pulse interval is one second. For a ten-second heartbeat, start with:

```powershell
.\.venv\Scripts\python.exe playground/vlock_bridge/server.py --heartbeat-seconds 10
```

The advertised watchdog becomes 30 seconds for that interval (three beats); the
default one-second interval uses five seconds. Intervals from 1 to 60 are supported.
The UI reads the advertised timeout. A Boolean pulse can be missed if a consumer
samples too slowly; the diagnostic counter or timestamp is another way to detect
progress without relying on observing every True/False edge.

The UI checks for counter progress using the browser's monotonic clock. A failed
request marks it Offline; an unchanged counter is Offline after the advertised timeout.
Duplicate responses do not renew that timer. A fresh advancing counter or new
session restores Online. Adapter badges also require recent publication progress,
not just an old Connected/Running label.

Integration fields:

| Interface | Online and heartbeat data |
| --- | --- |
| HTTP | `/api/v1/health`: `online`, `heartbeat_pulse`, diagnostic counter, session, timeout |
| MQTT | `vlock/v1/availability`: `online`, `heartbeat_pulse`, diagnostic counter, session, timeout |
| OPC UA | `Bridge/Online`, `Bridge/HeartbeatPulse`, `Bridge/HeartbeatIntervalSeconds`, counter, timeout, session |

An external consumer should mark its connection Offline on transport failure,
explicit offline status, or no heartbeat progress within the advertised timeout. Use
local elapsed time for that timeout. After connecting to MQTT, wait for counter
progress before treating a retained Online message as proof of live communication.
For OPC UA, require good tag quality as well as heartbeat progress. Do not use a
cached True as an indefinitely valid Online indication.

A stopped or frozen server cannot reliably send `online: false`. HTTP stops
responding; OPC UA closes or freezes until the client detects it; MQTT publishes
offline on graceful stop or through the broker's Last Will after failure detection.
The receiver's watchdog is therefore part of the contract. These are connection
health signals, not machine permissives or reset commands.

Protocol connection monitoring is separate from this optional application signal.
The MQTT library/broker handles keepalive packets and the configured Last Will;
OPC UA client/server libraries handle sessions and subscription keep-alives.
vLock is the MQTT publisher / OPC UA server. The receiving SCADA or other client
subscribes to topics or OPC UA nodes and handles their connection quality. Our
application heartbeat adds visibility of vLock's periodic task; it does not prove
that a camera or inference model is running.

### Read the actual pulse from PowerShell

This command uses an absolute executable path, so it works from any directory:

```powershell
& 'C:\Users\ec-en\Desktop\vLock-AI Vision\.venv\Scripts\uasubscribe.exe' -u 'opc.tcp://127.0.0.1:4845/vlock/' -n 'ns=2;s=Bridge/HeartbeatPulse'
```

Expect alternating `value=True` / `value=False`. Press Ctrl+C to stop. Namespace
index 2 is the current local endpoint's index; other deployments should resolve
the documented namespace URI. A relative `.\.venv` command instead requires
PowerShell to be in the project folder, not the Windows user home folder.

## Event-history retention

The UI requests and shows only the **latest 5 events**. By default, the database
keeps the latest **1,000 events**, pruning older entries on startup and after new
events. Change the retained count when starting the server:

```powershell
.\.venv\Scripts\python.exe playground/vlock_bridge/server.py --history-limit 1000
```

The supported limit is 5-100000. Superseded observation bodies are also removed
when they are referenced by neither retained events nor current signal state.
Each signal's latest observation is preserved, even if its original event is older
than the limit. This bounds history storage, not the number of configured signals.
SQLite reuses freed pages; its existing file may not immediately shrink.

Idempotency protection covers retained observations and current signal observations.
An old request ID outside that retained window may be treated as a new request.
External clients should send the original `observed_at`, TTL, ID and body on retries,
and avoid indefinite retries, so an expired historical input cannot become fresh.
The manual UI does not automatically retry uncertain writes.

The event API includes `retention_limit`, `stored_count`, `oldest_revision` and
`cursor_expired`. A client replaying after a pruned cursor must resynchronize from
the current asset snapshot; the missing history is no longer available. Revisions
continue increasing and are not renumbered by pruning. This is a bounded experiment
log, not a permanent audit archive.

## MQTT output

The app is an MQTT **publisher**, not a broker. Use a local broker such as
Mosquitto. Initial address: `127.0.0.1:1883`. Do not change the broker's existing
configuration merely to run this experiment. The UI accepts only loopback broker
addresses. MQTT 3.1.1 JSON is used; this is not a Sparkplug implementation.

Default topic prefix: `vlock/v1`.

| Topic | Payload |
| --- | --- |
| `vlock/v1/state` | Complete current snapshot, same shape as GET /api/v1/assets |
| `vlock/v1/assets/{asset_id}/state` | One asset, same shape as GET /api/v1/assets/{asset_id} |
| `vlock/v1/availability` | status, online Boolean, session ID, heartbeat timestamp/counter, timeout |

Publishes are retained, at QoS 1, approximately once per second while connected.
The UI reports Connected only after the broker acknowledges a snapshot batch.
Acknowledgement proves broker receipt, not consumption by SCADA or any machine action.
This is latest-state output, not guaranteed event replay; use the HTTP event API
for history. Repeated state messages and QoS duplicates must not trigger repeated
machine actions. Consumers can use session/revision/observation IDs for correlation.

An offline retained Last Will is configured, and orderly shutdown publishes offline
explicitly. On disconnection the publisher discards its client/queued messages and
reconnects with a fresh snapshot. It does not replay expired samples as new input.
MQTT timestamps and signal expiry keep their original meaning; publication is not
a new observation. Check availability, its age, state heartbeat and per-signal expiry.
A retained message alone is not proof of a live bridge. On an abrupt process loss,
broker Last Will timing is subject to connection/keepalive detection; consumers
still need their own communication timeout.

The bridge does not subscribe to commands or accept observations over MQTT in this
step. Change the prefix if another bridge owns the same topics. Old retained topics
under an earlier prefix remain at the broker and must not be used as live data.

For a local broker requiring credentials, set `VLOCK_BRIDGE_MQTT_USERNAME` and
`VLOCK_BRIDGE_MQTT_PASSWORD` in the server process environment before starting it.
The bridge does not read the root .env and never returns credential values to the
browser. No credentials are stored in transports.json. MQTT TLS and remote broker
access are not exposed by this version.

## OPC UA output

Enable **OPC UA** and use the default endpoint:

```text
opc.tcp://127.0.0.1:4845/vlock/
```

Connect a local OPC UA client (including an Ignition Gateway on this PC), select
NoSecurity/anonymous, and browse **Objects > vLock**. All application variables are
read-only. No username becomes an application administrator. There are no commands,
reset methods, or external observation writes. This local endpoint does not provide
encrypted/authenticated remote access.

Namespace URI: `urn:vlock:bridge:v1`. Resolve the URI rather than assuming a namespace
index. Stable string NodeIds are based on asset/source/signal IDs:

| NodeId string (within that namespace) | Type / meaning |
| --- | --- |
| `Bridge/Heartbeat` | String, UTC publication heartbeat |
| `Bridge/Online` | Boolean, availability through this endpoint; requires client watchdog |
| `Bridge/Status` | String, online/offline |
| `Bridge/HeartbeatCounter` | Int64, optional diagnostic beat count |
| `Bridge/HeartbeatPulse` | Boolean, periodic True/False application pulse |
| `Bridge/HeartbeatIntervalSeconds` | Double, configured pulse interval |
| `Bridge/OfflineAfterSeconds` | Double, recommended heartbeat timeout |
| `Bridge/SessionId` | String, process identity |
| `Bridge/Revision` | Int64, global event revision |
| `Bridge/Assets/{asset}/Inhibit` | Boolean with OPC UA quality |
| `Bridge/Assets/{asset}/InhibitKnown` | Boolean, whether inhibit is established |
| `Bridge/Assets/{asset}/ObservationStatus` | String: active/clear/unknown/stale |
| `Bridge/Assets/{asset}/Quality` | String: good/uncertain/unknown |
| `Bridge/Assets/{asset}/ReasonsJson` | JSON String with active/unavailable reasons |
| `Bridge/Assets/{asset}/StateJson` | Complete one-asset API response in one JSON String |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/Status` | Current signal status |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/Kind` | condition/measurement |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/ObservedAt` | Observation timestamp |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/ExpiresAt` | Observation expiry |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/ValueJson` | Original value as JSON String, with quality |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/Active` | Condition only: Boolean, with quality |
| `Bridge/Assets/{asset}/Signals/{source}/{signal}/NumericValue` | Measurement only: Double, with quality |

Nodes appear after the first observation and keep the same IDs across updates and
restarts. Updates run about every half second; this is not a hardware latency claim.
Browse names show asset and source/signal labels; the string NodeIds above can be
used directly. Arbitrary JSON measurements are available through ValueJson; numeric
measurements additionally use NumericValue. NumericValue is BadTypeMismatch for a
non-numeric value, rather than a good-quality zero. Double conversion can lose
integer precision; ValueJson preserves the JSON value.

The Inhibit node has Boolean datatype. When Unknown, its DataValue is null with
a bad status, and InhibitKnown=False; it never becomes a good-quality False.
Expiry uses BadNoCommunication;
other unavailable input uses BadWaitingForInitialData. A known active inhibit plus
an unavailable condition uses UncertainDataSubNormal. Measurement/condition values
also carry observation quality and their original source timestamp.

Clients must honor the OPC UA status code, InhibitKnown and a communication
watchdog. Never interpret the Boolean by itself as permission to operate.
StateJson preserves null and gives a coherent snapshot; separately read primitive
nodes are updated sequentially. A subscription or network failure also needs the
client's stale-data handling even if its last cached node value was good.

The same expiration logic is shared with HTTP and MQTT. An enabled adapter checks
freshness itself; leaving the UI closed does not prevent expiry publication.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s playground/vlock_bridge -p "test_*.py" -v
node --check playground/vlock_bridge/app.js
node playground/vlock_bridge/test_heartbeat.cjs
```

Tests use temporary databases and local HTTP servers, with no model or machine
requests. They cover aggregation, separate sources, measurements, unknown/stale
states, restart recovery, timestamp ordering, duplicate handling, concurrent
submissions, history cursors, HTTP routes, origin/host checks and input limits.
The optional HTTPS check generates a temporary certificate using OpenSSL (including
the Git for Windows copy when available) and verifies it with a trusted client
context. It skips that check if OpenSSL is absent; the bridge itself does not
require OpenSSL. No certificate or private key is added to the project.

For real MQTT round-trip/reconnect checks using an isolated temporary broker, install:

```powershell
.\.venv\Scripts\python.exe -m pip install -r playground/vlock_bridge/requirements-test.txt
```

Transport tests use temporary loopback ports. They do not reconfigure the installed
broker or send machine commands. They cover MQTT retained JSON, broker acknowledgement,
expiry, reconnect with fresh state, offline availability, and OPC UA read-only access,
typed measurements, quality changes and recovery. Missing optional packages cause
those transport checks to skip; report skips when evaluating a fresh installation.

Actual Ignition tag mapping, remote deployment and real model output remain
unverified. See the development log for actual adapter/client evidence.

Implementation references: [Paho client API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
and [OPC UA asyncio library](https://github.com/FreeOpcUa/opcua-asyncio).
