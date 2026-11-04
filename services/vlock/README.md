# vLock service

The working app now uses the validated durable observation store (`store.py`),
application heartbeat and direct internal `ObservationOutput` publisher. Current
state and bounded observation history are exposed through read-only REST routes
on the working application. Source is `vision`; asset ID is the stable zone ID;
signal ID is the reviewed output name. Original capture age determines expiry.

The original bridge experiment remains intact, including its OPC UA/MQTT adapters
and existing SCADA contract. Those external adapters are not started by this app
chapter. No machine command, worker-lock lifecycle, latch, reset or automatic
restart is implemented by the observation service. SCADA retains those controls.

Current REST contract, bound to loopback through web/application.py:

- GET /api/v1/assets and /api/v1/assets/{zone_id}: observation snapshots.
- GET /api/v1/events?limit=5&after=REVISION: bounded history with cursor expiry.
- GET /api/v1/health: application heartbeat, session and progress diagnostics.

Unknown and expired values cannot establish Clear. Counts are whole-frame counts,
not visitors or zone-only occupancy; valid zero differs from unavailable/null.
Signals discovered after configuration start Unknown until fresh inference.
Restart preserves history but invalidates all old current observations.

Per-zone monitoring history is configured separately (5–500 entries). The shared
observation history retains up to 1000 entries. Run one application process per
data directory. Consumers must check validity, timestamps and their own heartbeat
watchdog. Local publication is not external SCADA delivery or machine acknowledgement.

Renamed output streams remain in observation history. The application deletes a
zone's old current signal when its output is renamed, its kind changes or the zone is
removed (`Store.retain`, recorded as a `removed` event), so a leftover signal cannot
hold the asset at Unknown. Removed OPC UA nodes stay until restart with Bad quality.

`zone_tags.py` builds the fixed per-zone SCADA tags (`Bridge/Zones/<tag key>/...`,
MQTT `zones/<tag key>/state`, REST `/api/v1/zones`) from the zone manifest set by the
application and the current observations, plus the Ignition UDT export. See
[fixed zone tags](../../ignition/ZONE_TAGS.md).

## OPC UA and MQTT adapters

`transports.py` and `opc_client.py` are the bridge experiment's adapters with
package-relative imports and their regression tests. The working application runs
`Integrations` over its own observation store and starts/stops the OPC UA server and
MQTT publisher from the workspace integration profile. The NodeId contract
(`urn:vlock:bridge:v1`, `Bridge/Assets/<asset>/Signals/<source>/<signal>/...`) is
unchanged; the app's asset is the zone ID and its source is `vision`. Read-only
publication only: no command, latch or reset is implemented here.
