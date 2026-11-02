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

AND/OR rules, point/box object selection, second-check models, remote enable,
score filtering and external transport adapters are not wired yet. Unsupported
settings are rejected when saving a monitoring rule. Set minimum score to zero;
available positive object scores remain diagnostic, and Clear has no fabricated
confidence score. The working app uses no synthetic detections or latency values.
Worker window time and observation age are shown separately. Masks are displayed
on the exact analyzed frame, independently from the newer live camera preview.
Existing camera/photo tools on 5051 and bridge on 5055 are unchanged.
