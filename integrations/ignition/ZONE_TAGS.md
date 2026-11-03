# Fixed zone tags for SCADA

Every zone publishes the same tag names. Only the values change, so a SCADA
developer binds once. Changing the rule, the objects, the zone name or the output
name never moves a tag.

## Tag key

Each zone gets a short **tag key** (for example `A-101`) when its rule is first
saved, made from the zone name at that moment. The application owns the key: later
renames keep it, and the SCADA tags page shows it. Zones without a saved rule have no
key and no tags yet.

## Tags per zone

| Tag | Type | Meaning |
|---|---|---|
| Active | Boolean | Rule met. Bad quality when Unknown, and always for count zones. |
| State | String | `Active`, `Clear`, `Valid` (count zones) or `Unknown`. |
| Quality | String | `Good`, `Unknown` or `Stale`. |
| Reason | String | Why the zone has this state. |
| Count1 / Count2 | Int32 | Detections of Object1 / Object2 in the whole frame. Bad when Unknown or unused. |
| Score1 / Score2 | Double | Highest SAM score per object, 0-1. Diagnostic only: not a calibrated probability, never used by the rule. |
| ObservedAt | String | UTC time of the analysed frame. |
| AgeSeconds | Double | Seconds between ObservedAt and the update. |
| CheckSeconds | Double | SAM time of the last check. |
| ZoneName, ZoneId | String | Zone name and internal id. |
| OutputName, OutputType | String | Output name and type from the rule (`condition`, `event`, `count`). |
| Rule | String | The rule in plain words. |
| Object1 / Object2 | String | Objects SAM looks for; Object2 is empty for one-object zones. |

Unknown is never published as Clear: without a fresh result `Active`, the counts and
the scores carry Bad quality (a null value) and `State` is `Unknown`. Also watch the
bridge heartbeat (`Bridge/Online`, `Bridge/HeartbeatCounter`).

## Where the tags are

- **OPC UA** (read-only, this PC only, no security):
  `opc.tcp://127.0.0.1:<port>/vlock/`, namespace `urn:vlock:bridge:v1`, NodeId
  `Bridge/Zones/<tag key>/<tag>`, for example
  `nsu=urn:vlock:bridge:v1;s=Bridge/Zones/A-101/Active`.
- **MQTT** (retained JSON): `<topic prefix>/zones/<tag key>/state`, for example
  `vlock/v1/zones/A-101/state`. A removed zone's topic is cleared with an empty
  retained message.
- **REST**: `GET http://localhost:5056/api/v1/zones` and `/api/v1/zones/<tag key>`.

A zone removed from the workspace keeps its OPC UA nodes until the application
restarts, with `State=Unknown` and `Reason=Zone removed from the workspace.`

## Ignition import (UDT)

1. Gateway → Connections → OPC → Connections: add an OPC UA connection named
   `vLock Bridge` to `opc.tcp://127.0.0.1:4845/vlock/` (Anonymous, Security None).
2. In the app: Integrations → enable OPC UA → Save workspace.
3. SCADA tags → **Download Ignition UDT** (`vlock-zones.json`).
4. Designer → Tag Browser → Import Tags, choose the file. It adds the `vLockZone`
   UDT under Data Types, a `vLock` folder with one instance per zone (parameter
   `ZoneKey`) and the `vLock/Bridge` heartbeat tags.
5. For a new zone later: save its rule, then add one `vLockZone` instance with its
   tag key, or import a fresh file.

If the OPC UA connection has another name, change the `OpcServer` parameter of the
instances. The export follows Ignition's tag JSON format, but importing it into a
gateway has not yet been tested.

The older raw contract (`Bridge/Assets/<zone id>/Signals/vision/<output>/...`) is
still published for existing bindings, but its paths follow the output name. New
bindings should use the zone tags.
