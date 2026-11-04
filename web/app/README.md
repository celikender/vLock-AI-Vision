# Working Zones application

Double-click `Start vLock.cmd` in the project folder, or run from the project root:

```powershell
.\.venv\Scripts\python.exe web/application.py --open
```

Open http://localhost:5056. The app starts the local SAM 3.1 worker itself
(services/vision/sam_worker.py inside the existing Ubuntu/WSL CUDA environment,
loopback port 5052) and preloads the model; the zone header shows its status and
offers Start SAM after a failure. A worker that is already running is reused and
left running. A different program on port 5052 is reported, never stopped. The
worker log is `sam_worker.log` in the data directory. Closing the app window stops
a worker the app started. `--no-sam` runs without managing a worker.

Add a zone, choose the camera type and enter its private LAN address, connect, then
configure the zone with Muse or by hand. **Pi / HTTP** reads the Pi camera service's
original JPEGs. **RTSP** reads an IP camera (`rtsp://192.168.1.64:554/stream2`) with
its username and password in their own fields; the password is write-only and frames
are scaled to fit 1280×960 (see [camera sources](../../docs/CAMERA_SOURCES.md)). Workspace configuration is stored by the backend under
ignored data/application (copied once from the former playground location). Enable monitoring is available once SAM is ready
and a rule is saved. Only one local-SAM zone runs at once.

Current observations are recorded through services/vlock and exposed at
`/api/v1/zones` (the fixed zone tags), `/api/v1/assets` (raw signals by zone ID,
source `vision` and output name), `/api/v1/events?limit=5` and `/api/v1/health`.
Integrations can also start the OPC UA server and MQTT publisher described below.
No adapter sends a machine command.

Point/box object selection, rules with more than two objects, second-check models,
remote enable and score filtering are not wired. Unsupported settings are rejected when saving a rule.
Available positive object scores remain diagnostic, and Clear has no fabricated
confidence score. The working app uses no synthetic detections or latency values.
Worker window time and observation age are shown separately. Masks are displayed
on the exact analyzed frame, independently from the newer live camera preview.

Start only one application process per data directory. Monitoring always starts
disabled after restart. Changing settings requires Stop and completion of the
active local-worker window. The API rejects stale concurrent workspace revisions.
Camera HTTP authentication is not exposed in this UI yet. Backend services own
geometry, persistence, freshness, state, counts, output values and history. The
frontend handles editing, presentation and API requests only.

## Configure with Muse Spark

Type what to watch, for example "Alert SCADA when a hand is on the storage drawers
for half a second", and click **Configure with Muse**:

1. Muse Spark (META_MUSE_MODEL, default muse-spark-1.3) receives the request and the
   zone's current draft. With "Muse sees the camera view" ticked (default when the
   camera is connected) it also receives the newest original JPEG. Untick it to keep
   the frame on this PC.
2. Muse returns one proposal limited to what the runtime executes: one or two object
   phrases (with AND/OR),
   overlap/inside/absent relation, confirmation seconds, output type and name, and
   how to make the area: a region SAM can outline (`sam_object`, e.g. "conveyor belt"),
   its own estimated box (`muse_box`, only with the camera view), the whole view, or
   keep the current area. It also lists visible objects SAM could find.
3. For `sam_object`, the backend asks the local SAM worker to segment that phrase on
   the current frame (POST /segment/regions) and turns the largest mask into a polygon
   of at most 12 corners. The frame never leaves the PC for this step. If SAM is busy
   or finds nothing, Muse's box is used when available; otherwise you draw the area.
4. The proposal appears with a dashed outline on the camera. **Use this configuration**
   fills the rule and area and saves the rule. Enabling monitoring stays a separate
   click. Requests the runtime cannot execute come back as unsupported with a reason.

The backend rejects proposals it cannot execute instead of repairing them. One Muse
request at a time, no automatic retries, sanitized errors; the key never reaches the
browser. Set META_API_KEY in the root .env. The rule can still be edited manually
under **Edit rule manually**.

## Two-object rules

A zone can watch two objects, for example "person AND dog in the area" or "person OR
forklift". Muse proposes them from one sentence; manually, open **Edit rule manually**
and fill **Second object** with its condition and **Combine** (ALL (AND) / ANY (OR)).

For each 4-frame camera window the app runs one SAM prompt per object on the same
frames, one after another on the already loaded worker (no second model, unchanged
worker protocol). Each object is evaluated with its own condition on the same frame,
then combined; persistence and confirmation apply to the combined result as before.
If either object's result is missing, failed or stale, the zone is Unknown, never
Clear. One output per zone: a condition, an event, or, for count, one whole-frame
number per object (for example `{"person": 2, "dog": 1}`).

Observation shows **Check time**: both prompts together. Measured on the RTX 3070 Ti
Laptop GPU (8 GB): about 2.9 s for one object and 5.8 s for two. Because a new
two-object result arrives only every ~6.7 s, keep **Result expires after** at 15 s or
more; applying a two-object Muse proposal raises it to 15 s and the rule summary warns
if it is lower. More than two objects is rejected.

## Login, roles and audit

The first start shows **Create the admin account**; after that the app asks for a login
(HttpOnly, SameSite=Strict session cookie; 8 h idle, 24 h maximum; a restart logs
everyone out). Roles, enforced by the server on every request:

| Role | Can |
|---|---|
| viewer | See zones, cameras, SCADA tags and integrations. |
| operator | Also connect/disconnect cameras, switch monitoring on/off, restart SAM. |
| admin | Also change zones, rules, Muse, integrations, users and trusted OPC UA clients. |

Passwords (10+ characters) are stored as PBKDF2-SHA256 hashes in
`data/application/users.json`; five failed logins lock that username for five minutes.
Workspace settings → **Users and audit** adds or deletes users, changes your password and
shows the audit log (`data/application/audit.log`: logins, refusals and every change,
never passwords). The SCADA REST API (`/api/v1/...`) stays readable on this PC without a
login; set `VLOCK_API_TOKEN` in `.env` to require `Authorization: Bearer <token>`.

Other security measures: OPC UA network mode accepts only client certificates an admin
trusted (Integrations → Trusted SCADA clients; a refused client waits there), the SAM
weights must match the pinned SHA-256 in `services/vision/runtime/weights.sha256`
before they load, RTSP cameras use a write-only password, and the Pi camera service can
require a token (`VLOCK_CAMERA_TOKEN`, entered as the zone's camera token).

## Skills and Muse frame checks (experimental)

[Skills](../../skills/README.md) are scenario packages in `skills/` (a `skill.json` and a
`knowledge.md`). When you ask Muse to configure a zone, the three best-matching skills
and the site notes go to Muse as reference data; the proposal card shows the skill it
followed. A skill can add an optional **Muse frame check** for things SAM alone cannot
judge (a real person or a poster, helmets, camera blocked, stack light colour). It runs
only when the zone's *Allow Muse frame checks* box is ticked, sends a camera frame to
Meta, and writes its answer to the `VlmState`, `VlmReason` and `VlmCheckedAt` tags and
the Observation panel. SAM still decides Active / Clear / Unknown; the answer never
changes them.

## Reliability

- **SAM worker:** if a worker the app started crashes, stops answering (three missed
  health checks after it was ready) or fails warm-up, the app restarts it by itself,
  at most 3 times in 15 minutes, then shows the reason. Missing CUDA or weights are
  reported without retries. A GPU out-of-memory error during monitoring drops the
  model so the next check reloads it. Zones show Unknown until results return.
- **Damaged files:** a damaged `workspace.json` is replaced by its last good copy
  (`workspace.json.bak`, written on every save), or the app starts empty; a damaged
  history database or zone monitoring file is started again. Damaged files are kept
  as `<name>.damaged-<time>` and a notice explains what happened.
- **Clock:** observation order and expiry use a steady clock, so changing the PC clock
  cannot freeze an old Clear or reject fresh results.
- **One copy per data folder:** a second start with the same data folder, or on a port
  already in use, is refused with a message.
- **Monitoring watchdog:** a monitoring thread that stops unexpectedly turns the zone
  Unknown and stopped within 2 s, even with no browser open; an event file that cannot
  be written keeps events in memory instead of stopping monitoring.
- **Logs and outputs:** the SAM worker log rotates at 5 MB before each worker start
  (two old copies) and no longer logs every frame or health check. The OPC UA server
  restarts by itself with backoff after a failure such as a busy port.

## OPC UA and MQTT outputs

Integrations → enable **OPC UA** (Host server mode) and/or **MQTT** (client of a broker
on this PC), then click Save workspace. OPC UA **Access** is *This PC only* (127.0.0.1,
no security) or *Network* (a private address of this PC, Basic256Sha256 Sign & Encrypt
and a username/password from `.env`, no anonymous or unencrypted access) for SCADA on
another PC; see [fixed zone tags](../../ignition/ZONE_TAGS.md). The app starts or stops the adapters promoted
from the vLock Bridge experiment (services/vlock/transports.py) on the app's own
observation store. Saved enabled adapters restart with the app. The OPC UA server is
read-only at `opc.tcp://127.0.0.1:<port>/vlock/` with namespace `urn:vlock:bridge:v1`.
Every zone publishes the same fixed tags under `Bridge/Zones/<tag key>/` (Active,
State, Quality, Reason, counts, diagnostic scores, timing and the rule text); the tag
key is set when the rule is first saved and never changes, so renaming the zone or
output keeps SCADA bindings. MQTT publishes `<prefix>/zones/<tag key>/state` and REST
serves `/api/v1/zones`. SCADA tags shows the values and offers an Ignition UDT
download; see [fixed zone tags](../../ignition/ZONE_TAGS.md). The older
`Bridge/Assets/<zone id>/Signals/vision/<output>/...` nodes remain for existing
bindings, with heartbeat nodes under `Bridge/`. Stop the separate
bridge (port 5055) first if it uses the same OPC UA port. Client mode needs explicit
node mappings and stays in the bridge experiment.

## Configuration editing

Choose Rectangle and drag, or Polygon and click up to 12 corners. Close with the
first point or Finish area. Undo, cancel, clear, vertex dragging and keyboard
arrows are supported. Rejected geometry leaves the saved area unchanged. The
backend still validates the final polygon. Object clicking is documented only,
not displayed as an available selection tool. Original JPEG preview nodes stay
in place during drawing to avoid restarting the frame refresh pump.

Event condition exposes the existing overlap, entirely-inside and absence rules.
The sentence preview describes the saved fields; no prose is parsed as a rule.
A count output is a fresh whole-frame count and bypasses area/confirmation gating
for its numeric value. Condition and event outputs use the existing state rules.
Prompt reference: https://dev.meta.ai/docs/sam/segmenting

## Unified zone workspace

The Zones dashboard contains status/output cards with no camera images and makes
no camera-preview requests. Open a zone to configure and monitor it in one page:

1. Camera connection and one live camera view for drawing/editing the area.
2. SAM settings, with expandable configuration help above the rule fields.
3. The exact analyzed SAM frame, current outputs, event-to-output flow and history.

Desktop uses three columns; smaller screens reflow the same sections. Connection
settings collapse after connecting and can be reopened. Enable/disable monitoring
is at the top; Save rule validates through the existing service. Enabling requires
a connected camera and saved rule. Editing is locked while monitoring is enabled
or a worker window is finishing. Disabling remains accessible if the camera fails.

Runtime polling updates the results and controls without replacing camera geometry
or draft inputs. Unchanged analyzed images are retained while ages/output text
refresh. Recent events still shows five with expandable bounded history. No
backend inference, state, monitoring or integration contracts changed.

UI regression commands: `node web/test_zone_workspace.cjs` and
`node web/test_camera_preview.cjs` from the project root.

## Stable observation view and SCADA visibility

The right column starts with Observation, aligned with Camera & area. Only its
text and event list are patched during polling. The SAM viewer stays mounted;
replacement images are fetched/decoded before swapping onto the same element.
Only the newest requested update is retained, with one request/decode in flight.
The previous decoded image remains visible during a slow or failed update. If
fresh evidence is unavailable, it is labeled as a last image, not a current
observation. Backend state/validity remain authoritative. This is not an inference
latency improvement. `node web/test_analyzed_preview.cjs` exercises this lifecycle.

Show drawn area controls only outline/vertex visibility. It remains usable while
monitoring; hiding the outline never disables monitoring or removes the saved
geometry. Starting a new drawing makes the outline visible again. The event-flow
card is removed; five recent events and expandable history remain.

SCADA tags replaces System monitor in the sidebar. It lists each zone's fixed tag
key, output name and MQTT topic, the fixed tags with their local values and
OPC UA NodeIds (`Bridge/Zones/<tag key>/<tag>`), and the Ignition UDT download.
False, zero and unavailable/null stay distinct. Values are read from the app's own
REST output, not OPC readbacks or proof of delivery; the Delivery column shows
whether the app's OPC UA server is live (see OPC UA and MQTT outputs above).
Client mode needs explicit node mappings and is not offered in this app.

Integrations restores compact OPC UA server/client, MQTT and HTTP profile fields,
local API troubleshooting and a link to the independent bridge connection/status
UI. Profile edits persist through the existing Save workspace contract; saving an
enabled OPC UA server or MQTT profile now starts that adapter, and its real status
is shown. API availability is checked live. Profile forms are not replaced by
background status polling.

## Aligned views, live camera status and workspace folders

The three lanes have distinct visual boundaries: Camera & area, Help &
configuration, and Observation. Both image viewports use the same shared grid row
and camera aspect ratio, including when connection settings expand. The compact
zone header keeps controls close. Hardware/performance metrics sit below the SAM
image rather than shifting that image upward.

Connected cameras now keep one original-JPEG latest-frame buffer continuously
fresh, independently from browser viewers and SAM windows. Consumers share the
buffer without queues or extra upstream requests. Disconnect stops PC polling;
it does not stop the Pi service. Preview pacing targets 20 FPS; the measured local
stream in this check was about 14 FPS. Backend status owns connection truth.
See docs/CAMERA_PERFORMANCE.md for measurements and limits.

Observation shows initialization while waiting for its first result, actual
window time, and available host CPU/GPU/VRAM diagnostics. Diagnostics run off the
HTTP path; unavailable metrics remain absent and no hardware improvement is
promised after a fixed warm-up time. Existing SAM and freshness rules are retained.

Workspace settings is first in navigation and the workspace name links to it.
SCADA tag paths no longer depend on the workspace, zone or output names: each zone
publishes under its fixed tag key (see [fixed zone tags](../../ignition/ZONE_TAGS.md)).
Names such as person_detect_A-101 are accepted as output names. OPC UA publication
of the fixed tags is tested locally with an OPC UA client; the UDT import and
delivery into the owner's Ignition are not yet verified.
