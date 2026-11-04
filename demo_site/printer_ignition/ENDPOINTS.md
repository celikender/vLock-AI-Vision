# SCADA and printer endpoint inventory

Checked against the local source and public references on November 4, 2026.
The printer protocol is firmware/model dependent. There is no claim that every
command below is supported by this P1S. Unused interfaces were researched, not probed.

## vLock-AI Vision: current local implementation

| Interface | Address / resource | Consumer behavior |
|---|---|---|
| OPC UA server, local default | `opc.tcp://127.0.0.1:4845/vlock/` | Read-only, enabled in app Integrations. |
| OPC UA namespace | `urn:vlock:bridge:v1` | Use namespace URI, not a hardcoded namespace index. |
| Zone node | `nsu=urn:vlock:bridge:v1;s=Bridge/Zones/<TagKey>/<Tag>` | Fixed key survives renaming. |
| Imported Ignition zone | `[default]vLock/<TagKey>/State`, `/Quality`, `/Reason` | Diagnostic display only; the site developer defines the reaction. |
| Imported heartbeat | `[default]vLock/Bridge/Online`, `/HeartbeatCounter` | Require Good OPC quality and counter motion; reject a frozen Clear. |
| MQTT broker default | `127.0.0.1:1883` | App publishes to a separately running local broker; this is not the printer broker. |
| MQTT zone | `vlock/v1/zones/<TagKey>/state` | Retained JSON; keys include State, Quality, Reason, ObservedAt. |
| MQTT health | `vlock/v1/availability` | Retained JSON and offline last will; also verify heartbeat/time locally. |
| MQTT snapshot | `vlock/v1/state`, `vlock/v1/assets/<id>/state` | Existing aggregate/raw observation interfaces. Prefer fixed zones for new bindings. |
| REST zones | `GET http://localhost:5056/api/v1/zones`, `/api/v1/zones/<TagKey>` | Read-only; bearer token required when configured on Setup. |
| REST diagnostics | `GET /api/v1/health`, `/api/v1/assets`, `/api/v1/assets/<id>`, `/api/v1/events?limit=5&after=<revision>` | Local app host/authorization checks apply. |
| Ignition UDT download | `GET /api/app/ignition/vlock-zones.json` | Requires logged-in app session. Use the SCADA tags download button. |

There is no product Reset/Resume endpoint: SCADA owns the latch and machine commands.
Screen Start/Stop/Reset run the customer Gateway site logic. There is no reverse
control channel into vLock; see [DEMO_SETUP.md](DEMO_SETUP.md).
This demo consumes vLock over OPC UA, and uses MQTT/TLS for the physical printer.
It does not require an MQTT module in Ignition. If choosing MQTT for vLock instead,
map broker documents into equivalent zone/heartbeat tags and enforce freshness;
that alternative mapping is not implemented by this package.

The app's network OPC UA option requires encrypted authenticated access and mutual
certificate trust; see [ZONE_TAGS.md](../../ignition/ZONE_TAGS.md). The default HTTP
app and connector endpoints are loopback-only. Remote Perspective clients receive
Gateway data; localhost URLs are never placed in the client image source.

## Local printer connector: routes implemented in this repository

Base: `http://127.0.0.1:8876`. Gateway-side HTTP only; browser Origin is rejected.

| Route | Purpose |
|---|---|
| `GET /health` | Service/configuration presence; never returns credentials. |
| `GET /status` | MQTT connection, report freshness, actual state, temperatures, progress, remaining_seconds, file_name, fault, camera availability. |
| `GET /camera.jpg` | Latest original JPEG, or HTTP 503 without a fresh frame. |
| `POST /command` | JSON `{"action":"Pause","id":"<unique-id>"}`; request IDs deduplicate within the connector process. |

Connector actions: `Pause`, `Resume`, `Stop`, `Reset`, `Start`. The new screen exposes
only Pause/Resume/Stop. Connector Reset reconnects communications and does not clear
printer faults. Screen Reset clears the SCADA latch and never calls connector Reset.
Connector Start can launch a configured microSD job, so it is intentionally absent
from this screen. A connector acknowledgement and an observed state are distinguished
in feedback. Credentials remain in the connector's local private `.env`.

## Native P1S interfaces and researched command families

These are community protocol observations, not a manufacturer-supported public API
guarantee. Interface inventory from original protocol research:
[MQTT](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md),
[camera](https://github.com/Doridian/OpenBambuAPI/blob/main/video.md),
[FTPS](https://github.com/Doridian/OpenBambuAPI/blob/main/ftp.md).

| Interface | Endpoint |
|---|---|
| MQTT/TLS | `<printer-ip>:8883`; username `bblp`, private LAN access code |
| Reports / requests | `device/<serial>/report`, `device/<serial>/request` |
| P1S camera | TLS TCP `<printer-ip>:6000`, framed JPEG; not native HTTP or RTSP |
| File transfer | Implicit FTPS `<printer-ip>:990` |

Research command index (availability varies):

| Family | Names |
|---|---|
| Telemetry/version | `pushing.pushall`, `print.push_status`, `info.get_version` |
| Job | `print.pause`, `print.resume`, `print.stop`, `print.project_file`, `print.gcode_file`, `print.skip_objects` |
| Settings/motion | `print.print_speed`, `print.gcode_line`, `print.calibration`, `print.print_option`, `print.unload_filament` |
| AMS | `print.ams_change_filament`, `print.ams_get_rfid`, `print.ams_user_setting`, `print.ams_filament_setting`, `print.ams_control` |
| System | `system.ledctrl`, `system.get_access_code`, `system.set_accessories` |
| Camera | `camera.ipcam_record_set`, `camera.ipcam_timelapse`, `xcam.xcam_control_set` |
| Firmware | `upgrade.upgrade_confirm`, `upgrade.consistency_confirm`, `upgrade.start`, `upgrade.get_history` |

Research does not establish P1S support for X1/LIDAR features or fault-reset commands.
The demo sends no motion, heating, firmware, AMS, access-code, file-upload or new-job
commands. It continues using its tested telemetry/control subset.

Bambu's [security white paper](https://cdn1.bambulab.com/trust-center/file/bambulab-security-whitepaper-en.pdf)
describes Developer Mode for third-party MQTT access. Successful telemetry does not
prove control authorization on a given firmware; verify Pause/Resume on the actual printer.
No firmware/mode changes were made in this session.

## Cloud interfaces, reference only

Cloud is unnecessary for this LAN demo. The research inventory includes
`https://api.bambulab.com` and `us.mqtt.bambulab.com:8883`; account/device/task routes
are listed in the [original cloud reference](https://github.com/Doridian/OpenBambuAPI/blob/main/cloud-http.md).
They are undocumented account APIs subject to change, not local printer HTTP endpoints.
No cloud login, credentials, requests or subscriptions were added.

Perspective supports embedded base64 image sources:
[official Image component documentation](https://docs.inductiveautomation.com/docs/8.3/appendix/components/perspective-components/perspective-display-palette/perspective-image).
That is the transport used for the optional camera panel.
