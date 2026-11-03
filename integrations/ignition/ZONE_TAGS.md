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
| Skill | String | Skill (scenario package) the zone follows, or empty. See [skills](../../skills/README.md). |
| VlmState | String | Answer of the optional Muse frame check (for example `yes`, `no`, `unsure`, `usable`, `red`), or `off`, `pending`, `error`. Advisory: never changes Active or State. |
| VlmReason, VlmCheckedAt | String | The check's one-sentence reason and UTC time. |

Unknown is never published as Clear: without a fresh result `Active`, the counts and
the scores carry Bad quality (a null value) and `State` is `Unknown`. Also watch the
bridge heartbeat (`Bridge/Online`, `Bridge/HeartbeatCounter`).

## Where the tags are

- **OPC UA** (read-only), namespace `urn:vlock:bridge:v1`, NodeId
  `Bridge/Zones/<tag key>/<tag>`, for example
  `nsu=urn:vlock:bridge:v1;s=Bridge/Zones/A-101/Active`. Two access modes
  (Integrations → OPC UA → Access):
  - **This PC only** (default): `opc.tcp://127.0.0.1:<port>/vlock/`, no security,
    anonymous. For SCADA on the same PC.
  - **Network**: `opc.tcp://<this PC's address>:<port>/vlock/`, Basic256Sha256
    Sign & Encrypt only and a username login only (no unencrypted or anonymous
    access). For SCADA on another PC. Set `VLOCK_OPCUA_SERVER_USERNAME` and
    `VLOCK_OPCUA_SERVER_PASSWORD` (12+ characters) in `.env` first, and allow the
    TCP port in Windows Firewall for the plant network. The server then listens only
    on that address, so SCADA on the same PC also uses it instead of 127.0.0.1. The
    self-signed server certificate is created once in `data/application/opcua/`
    (not in Git) and its SHA-1 fingerprint is shown on the Integrations page.
- **MQTT** (retained JSON): `<topic prefix>/zones/<tag key>/state`, for example
  `vlock/v1/zones/A-101/state`. A removed zone's topic is cleared with an empty
  retained message, also when it was removed while MQTT was off: on every connection
  the publisher reads the state topics still retained under its prefix and clears
  those that no zone uses. Give each vLock installation its own topic prefix. On a
  normal stop every zone is republished as `Unknown` ("MQTT publisher stopped");
  after a crash only `<prefix>/availability` turns offline (last will), so consumers
  must check availability and `ObservedAt`.
- **REST**: `GET http://localhost:5056/api/v1/zones` and `/api/v1/zones/<tag key>`.

A zone removed from the workspace keeps its OPC UA nodes until the application
restarts, with `State=Unknown` and `Reason=Zone removed from the workspace.`

## Ignition import (UDT)

1. In the app: Integrations → enable OPC UA, choose the Access → Save workspace.
2. Gateway → Connections → OPC → Connections: add an OPC UA connection named
   `vLock Bridge`.
   - This PC only: `opc.tcp://127.0.0.1:4845/vlock/`, Security None, Anonymous.
   - Network: discover `opc.tcp://<vLock PC address>:4845/vlock/`, choose
     Basic256Sha256 / SignAndEncrypt, enter the username and password, then trust
     the vLock server certificate when Ignition reports it. Compare its SHA-1
     fingerprint with the one on vLock's Integrations page. vLock also needs to
     accept Ignition: it accepts any client certificate with the correct login.
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
