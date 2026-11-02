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

Renamed output streams remain in observation history and their old current paths
become unknown on Stop/expiry. Use the configured signal path rather than assuming
that a multi-stream asset aggregate has become Clear. Stream retirement and adapter
mapping migrations need an explicit later contract.
