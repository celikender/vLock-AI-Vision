# vLock Bridge as an Ignition OPC UA client

> **Archived reference.** OPC UA client mode lived in the standalone vLock Bridge
> experiment, which was retired with the playground. The working application hosts
> OPC UA in server mode only (Integrations). The bridge code remains in git history
> (commit 16f210a, `playground/vlock_bridge/`); the commands below refer to it.

The experimental bridge now has two selectable OPC UA modes:

- **Host server**: the existing read-only bridge endpoint; Ignition subscribes.
- **Connect to server**: the bridge reads explicitly mapped nodes and writes
  observation results into explicitly mapped writable nodes on a local server.

Only one mode runs at a time. Existing saved settings migrate to server mode.
The client has been tested with isolated OPC UA servers, including encrypted
username authentication, certificate mismatch rejection, bad quality, expiry,
disconnect and reconnect. Live Ignition client authentication and Memory-tag
read/write have not yet been verified. The existing detection-to-Pause workflow
uses server mode and is separately owner-tested.

## Local Gateway discovery

On November 1, 2026, read-only discovery found Ignition at
`opc.tcp://127.0.0.1:62541`, advertising **Basic256Sha256 / SignAndEncrypt** and
**UserName** authentication. The Gateway web listener was on port 8088.
Bridge listeners 4845 and 5055 were not running at that check.

No Gateway settings or machine tags were changed during discovery.

## Prepare certificates

From the project root:

```powershell
.\.venv\Scripts\python.exe playground/vlock_bridge/prepare_opc_client.py --fetch-server-certificate
```

This creates `client.der` and `client-key.pem` under ignored
`playground/data/vlock_bridge/opcua/`. It retrieves the Gateway's public
certificate into `ignition-server.der` and prints its SHA-256 fingerprint.
Compare that fingerprint with the certificate shown/exported by the Gateway
before trusting it. Discovery alone does not establish trust. The helper refuses
to replace a different stored server certificate. Share only `client.der` with
Ignition; keep the private key local.

In Ignition's Gateway, Connections > OPC > OPC UA Server Settings, configure
**Expose Tag Providers** to expose Memory tags. In the OPC UA security/certificate
settings, import/trust the bridge's `client.der`. Use an OPC UA user with the
necessary Browse/Read/Write permissions for the intended test tag provider.
Keep the Gateway's encrypted endpoint enabled. Do not enable anonymous access
or change its security policy to make this client work.

Reference: [Ignition OPC UA server settings and permissions](https://www.docs.inductiveautomation.com/docs/8.3/ignition-modules/opc-ua/ignitions-opc-ua-server).

## Start with credentials in the process environment

Run these in the same PowerShell terminal. The credential dialog keeps the
password out of command history. The bridge does not read or change the project
`.env` and never returns OPC UA credentials or private-key contents to the UI.

```powershell
$opcCredential = Get-Credential -Message 'Ignition OPC UA user'
$env:VLOCK_BRIDGE_OPCUA_USERNAME = $opcCredential.UserName
$env:VLOCK_BRIDGE_OPCUA_PASSWORD = $opcCredential.GetNetworkCredential().Password
$env:VLOCK_BRIDGE_OPCUA_CERTIFICATE = (Resolve-Path '.\playground\data\vlock_bridge\opcua\client.der').Path
$env:VLOCK_BRIDGE_OPCUA_PRIVATE_KEY = (Resolve-Path '.\playground\data\vlock_bridge\opcua\client-key.pem').Path
$env:VLOCK_BRIDGE_OPCUA_SERVER_CERTIFICATE = (Resolve-Path '.\playground\data\vlock_bridge\opcua\ignition-server.der').Path
.\.venv\Scripts\python.exe playground/vlock_bridge/server.py
```

Open <http://localhost:5055>. Select **Connect to server**, endpoint
`opc.tcp://127.0.0.1:62541`, and **Basic256Sha256 / SignAndEncrypt**. Enable OPC UA
and Apply with empty mappings first to test the session. The application URI
in the client certificate is `urn:vlock:bridge:client`.

Credentials and certificate paths belong to the bridge process environment;
changing them requires restarting that process. A service needs its own environment.
Client mode currently connects to loopback endpoints only. No automatic fallback
to unencrypted security is performed. The None option is for isolated local tests.

## First read/write test

Create dedicated Memory tags in a new `vLockBridgeClientTest` folder, with no
machine-control scripts attached:

| Tag | Type | Initial value |
| --- | --- | --- |
| Running | Boolean | false |
| Inhibit | Boolean | true |
| InhibitKnown | Boolean | false |
| StateJson | String | empty string |
| HeartbeatPulse | Boolean | false |

Browse the exposed provider using an authenticated OPC UA browser to obtain
the actual Node IDs. The bridge form currently accepts explicit Node IDs; an
interactive node browser is not implemented. Both `ns=...` and `nsu=...` forms
are accepted; namespace URIs are resolved again on reconnect. The following
IDs are placeholders, not confirmed Ignition paths.

Read mappings:

```json
[
  {"label":"machine_running","node_id":"ns=2;s=REPLACE_WITH_RUNNING_NODE_ID"}
]
```

Write mappings:

```json
[
  {"asset_id":"client_test","field":"inhibit","node_id":"ns=2;s=REPLACE_WITH_INHIBIT_NODE_ID","known_node_id":"ns=2;s=REPLACE_WITH_KNOWN_NODE_ID"},
  {"asset_id":"client_test","field":"state_json","node_id":"ns=2;s=REPLACE_WITH_STATE_NODE_ID"}
]
```

Set the separate **Boolean heartbeat Node ID** to the actual HeartbeatPulse
node. Applying settings starts the configured exchange immediately. Up to 16
read mappings and 16 write mappings are accepted. Read targets cannot overlap
write targets. Resolved aliases are checked before writing. Output datatypes
are validated before the first write; the client never creates remote nodes.

Change Running in Designer and observe its value, quality, source timestamp
and receipt timestamp in bridge readbacks. Readbacks are diagnostic only and
are not imported into bridge observations or used to drive monitoring rules.
Only good-quality scalar values are shown as available; arrays and structures
are not supported in this first step. A good read confirms the server's value,
not an independent assessment of the underlying device's freshness.

In the bridge manual form, choose asset `client_test`, source `manual`, signal
`person_in_zone`. Publish Active, then Clear. Confirm the mapped Memory tags.
Let the observation expire and verify InhibitKnown becomes false, while
StateJson reports stale/unknown. Publishing manual data is a simulation.

## Receiver validity and failure handling

The client polls/exchanges approximately every 500 ms. It writes only current
snapshots and has no offline replay queue. The heartbeat is written only after
all configured operations have succeeded. A timeout or rejected write makes
the adapter Offline and starts reconnect attempts. A network timeout can leave
an uncertain or partially applied write; these are state updates, not commands.

For Boolean output, the bridge first writes InhibitKnown=false. It then writes
Inhibit and finally InhibitKnown=true only when the asset has good quality and
a known inhibit. Unknown, uncertain or stale observations leave Known=false;
the old Inhibit value must then be ignored. These separate writes are not atomic.
Do not trigger actions on Known transitions alone.

Ignition must combine Known, OPC quality and a receiver-side heartbeat watchdog
before consuming Inhibit. Known can remain true after transport loss because a
disconnected client cannot invalidate a remote tag. Require heartbeat progress
within the bridge's advertised timeout (five seconds by default; longer if the
heartbeat interval is changed). Poll quickly enough to see the pulse toggles.
Without a watchdog, cached Memory values cannot establish freshness.

StateJson includes observation status, timestamps and expiry in the full asset
snapshot; missing assets are explicitly unknown. Consumers must still use the
heartbeat watchdog. A successful write is a server acknowledgement, not a
machine acknowledgement. SCADA/PLC retains machine commands, worker locks,
interlocks, latches and resets. This step adds no Pause, Resume or reset writes.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s playground/vlock_bridge
node --check playground/vlock_bridge/app.js
node playground/vlock_bridge/test_heartbeat.cjs
```

The transport tests use isolated local endpoints and temporary data. They do
not log into Ignition or send printer commands.
