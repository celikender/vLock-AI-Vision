# Monitoring Setup MVP

This module is integrated into the existing PC application at
http://localhost:5051/monitoring. It reuses the existing Pi snapshot relay and SAM
3.1 four-frame video adapter. It is not a separate application server. The
camera/photo tools remain at http://localhost:5051/ and the older playground
experiments remain available.

## Run

From separate PowerShell terminals in the project directory:

```powershell
.\playground\segmentation\start_local.ps1
```

```powershell
.\.venv\Scripts\python.exe web/server.py
```

1. Open **Monitoring Setup**, enter the Pi IP or HTTP URL and Connect Camera.
2. Enter a detection phrase such as `person`.
3. Name the zone. Choose Draw polygon / Draw zone and click 3–32 points on the live
   frame. Finish the zone, then drag vertices to adjust. Undo/Delete are available.
4. Select a condition, overlap threshold and persistence duration.
5. Select Trigger warning event or Record event only. Save setup, then Start
   Monitoring. Stop ends monitoring; it does not stop the Pi camera service.

Apply changes to the detection target while running with **Apply**. The saved zone
is independent of the text prompt. Old prompt results are discarded, observation
state resets, and the existing loaded GPU model is reused. Camera, polygon and
rule edits require monitoring to stop and its in-flight window to finish.

## Implemented behavior

- Original Pi JPEG transport is reused without re-encoding input frames. Four
  fresh frames are collected only when SAM is ready. Preview and inference are
  independent; no ever-growing camera frame queue is introduced.
- SAM masks, available boxes, IDs, scores and per-frame JSON are preserved. Masks
  are shown on the exact analyzed camera frame, with the saved polygon and boxes.
  The independently refreshed live view is used for drawing. Old masks are not
  projected onto a newer unrelated frame.
- Polygon vertices are saved in original camera-pixel coordinates with their
  frame size. Self-intersecting, duplicate, tiny and out-of-frame polygons are
  rejected. Changing camera address or detecting a new resolution on reconnect
  clears the old zone; inference at the wrong resolution yields Unknown.
- Overlap is `mask pixels inside polygon / total object mask pixels`, computed
  from actual lossless SAM RLE masks. Bounding-box intersection is not used as a
  substitute. Entire object inside requires all object mask pixels inside the
  zone. Object absent means no detected object meets the configured overlap
  threshold in the zone, rather than absence everywhere in the image.
- At least two fresh observations must span the configured persistence duration
  before either an active or inactive condition is confirmed. Camera timestamps,
  duplicate frames, lost inference, stop and prompt revisions are handled
  separately from model geometry. Missing data never establishes absence.
- Normal means the rule is confirmed inactive. Warning means it is confirmed
  active. Unknown means the rule cannot currently be established. Warning action
  sets `warning_active`; Record event only records a rule transition without
  setting this warning output. No physical machine command is sent.
- The latest 100 events and saved camera/target/zone/rule survive restart. The
  application starts stopped and requires camera reconnection; it never resumes
  monitoring automatically. In-flight results after Stop are discarded.

## Limits and honest capability reporting

This MVP accepts the existing Pi HTTP feed using private LAN IPv4 addresses, with
optional HTTP Basic credentials. It is not a generic RTSP, HTTPS, Digest-auth or
ONVIF implementation. Credentials are kept in the ignored local configuration
file and sent only by the backend to the selected camera. They are never returned
in configuration/status JSON, stored in browser code, or included in events/logs.
The actual Basic-auth path has offline transport tests; the owner's Pi demo does
not require credentials.

Manual polygons are implemented. Although the installed SAM session API exposes
interactive prompts, the existing worker endpoint accepts text-only windows.
Point/box object selection and same-session editing have not been exposed or
validated for this UI. Its disclosure states this explicitly. No model/runtime
replacement or extra checkpoint is needed for manual zones. No LLM is used by
monitoring. A SCADA-tag action remains disabled until an adapter is configured.

This uses sampled windowed inference, not continuous identity tracking. Object
IDs are session-scoped and are not required for these zone rules. Persistence
spans sampled observations; it is not proof of continuous occupancy between them.
Inference older than **10 seconds** becomes Unknown and resets confirmation.
Current GPU/window latency can cause Unknown intervals between otherwise fresh
results. A persistence duration longer than the available fresh observation span
may never confirm. Do not raise freshness limits just to disguise inference delay.

## Local storage and API

Ignored files under `playground/data/monitoring/` hold `configuration.json` and
the latest 100 `events.json` entries. Configuration writes are atomic. The public
camera view exposes only a `credentials_configured` boolean. Invalid saved
configuration is retained, shown as Unknown, and requires an explicit Save setup
to replace; it does not prevent the original camera/photo tools from starting.

All routes use the existing loopback Host/Origin checks:

| Route | Purpose |
|---|---|
| `GET /api/monitoring/status` | Public saved setup, current health/rule state, overlay, events |
| `GET /api/monitoring/snapshot` | Original camera JPEG and freshness metadata |
| `GET /api/monitoring/results?after=ID` | Latest eight per-frame mask results and zone measurements |
| `POST /api/monitoring/connect` | Connect and save camera configuration |
| `POST /api/monitoring/save` | Validate/save camera, target, zone and rule |
| `POST /api/monitoring/start` | Start the saved rule |
| `POST /api/monitoring/stop` | Stop and discard pending results |
| `POST /api/monitoring/prompt` | Change `sam_prompt`, preserving the approved zone |

Each frame keeps the SAM fields and adds `output_id`, `zone_detections`, the raw
`condition_matched` geometry, the rule state at publication, and refreshed age/
staleness. Historical frame state is not the current alarm state; use status and
`warning_active` for the current result. Private test evidence stays under
`playground/outputs/` and is not published.

## Verification — 2026-10-29

Offline checks cover configuration restart recovery, credential redaction and
transport, unsafe URLs, polygon geometry, real-mask versus box intersection,
inside/absent conditions, persistence, stale/future/duplicate observations,
warning/event-only actions, prompt changes, cancellation, invalid stored config,
and the new HTTP routes. Existing camera/photo and segmentation tests are kept.

The browser demo connected the real Pi at `192.168.1.254:8080`, drew and adjusted
a four-vertex demo zone, saved it, and started the `person` rule. Real SAM masks
had approximately 44% of their pixels inside the zone (10% threshold, 0.25-second
demo persistence). Fresh observations reached Warning with `warning_active: true`;
cold results remained Unknown. Changing the target to `forklift` retained the zone,
returned fresh empty-object frames and reached Normal with `warning_active: false`.
Both phases reported `model_loads: 1`. This validates the application flow, not
ground-truth object recognition accuracy or safety-rated machine protection.

The demo configuration is explicitly named **Demo Zone — full view**; replace it
with the actual approved equipment zone before evaluating a real scenario. A
physical camera-unplug test, credential-protected hardware, and recognition
accuracy remain for owner testing. SCADA output and SAM-assisted zone selection
are not implemented.

Run checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s playground/monitoring -p 'test_*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s web -p 'test_*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s playground/segmentation -p 'test_*.py' -v
node --check web/monitoring.js
```

To observe an explicitly started live rule and save private per-frame evidence:

```powershell
.\.venv\Scripts\python.exe playground/monitoring/record_run.py --until Warning
```
