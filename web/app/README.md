# Working Zones application

Camera/workspace and local SAM monitoring checkpoint. Start from the project root:

```powershell
.\.venv\Scripts\python.exe web/application.py
```

Open http://localhost:5056. Add a zone, enter the Pi camera's actual private LAN
address, save/connect, and draw an area over original camera frames. Workspace
configuration is stored by the backend under ignored playground/data/application.
The approved simulated prototype stays separate on port 5070.

Start the existing local SAM worker separately with
`.\playground\segmentation\start_local.ps1`. Connect the camera, draw an area,
choose one object phrase and geometric condition, save the zone and explicitly
enable monitoring. Only one local-SAM zone runs at once. The configuration screen exposes the structured target/area/relation/persistence
fields that define the runtime rule. Older free-text descriptions are preserved
in saved data but are not executed or shown as editable programs. Persistence and validity are evaluated from fresh captures.

Current observations are recorded through services/vlock and exposed at
`/api/v1/assets`, `/api/v1/events?limit=5` and `/api/v1/health`. They use stable zone
IDs, source `vision` and the configured output name. Publication is local and
does not send a machine command. Integration settings show the available REST
contract and distinguish the still-unwired OPC UA/MQTT adapters.

AND/OR rules, point/box object selection, second-check models, remote enable,
score filtering and external transport adapters are not wired yet. Unsupported
settings are rejected when saving a monitoring rule. A draft with unsupported options offers an explicit reset to supported settings;
its target, area, description and output are preserved. Available positive object scores remain diagnostic, and Clear has no fabricated
confidence score. The working app uses no synthetic detections or latency values.
Worker window time and observation age are shown separately. Masks are displayed
on the exact analyzed frame, independently from the newer live camera preview.
Existing camera/photo tools on 5051 and bridge on 5055 are unchanged.

Start only one application process per data directory. Monitoring always starts
disabled after restart. Changing settings requires Stop and completion of the
active local-worker window. The API rejects stale concurrent workspace revisions.
The first chapter deliberately accepts only a private-LAN Pi HTTP feed and one
active local-SAM zone. Camera HTTP authentication is not exposed in this UI yet;
existing credential-bearing experiment configurations are not imported.

The earlier approved UI remains at playground/combined_app on port 5070. No
experiment has been deleted or redirected to this runtime. Backend services own
geometry, persistence, freshness, state, counts, output values and history. The
frontend handles editing, presentation and API requests only. Its polygon checks
are editing assistance; the backend performs the authoritative validation.

## Configuration editing

Configuration help is a provider-neutral local reference chat with topic-matched
answers. It calls no language model or cloud service, changes no settings, and
keeps only a bounded in-memory conversation. It explains single-concept prompts,
Unknown, confirmation, drawing and the limits of pattern recognition. SAM can
segment a named object; arbitrary patterns, gestures and light-on state need a
separate validated measurement or classifier. `hand and person` is not an app AND
rule. Multiple concepts and Boolean combinations remain unwired.

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
