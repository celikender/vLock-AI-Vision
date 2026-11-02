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
enable monitoring. Only one local-SAM zone runs at once. The free-text description
is not executed; the structured target/area/relation/persistence fields define
the runtime rule. Persistence and validity are evaluated from fresh captures.

Current observations are recorded through services/vlock and exposed at
`/api/v1/assets`, `/api/v1/events?limit=5` and `/api/v1/health`. They use stable zone
IDs, source `vision` and the configured output name. Publication is local and
does not send a machine command. Integration settings show the available REST
contract and distinguish the still-unwired OPC UA/MQTT adapters.

AND/OR rules, point/box object selection, second-check models, remote enable,
score filtering and external transport adapters are not wired yet. Unsupported
settings are rejected when saving a monitoring rule. Set minimum score to zero;
available positive object scores remain diagnostic, and Clear has no fabricated
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
