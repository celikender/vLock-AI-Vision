# Working Zones application

Camera/workspace checkpoint. Start from the project root:

```powershell
.\.venv\Scripts\python.exe web/application.py
```

Open http://localhost:5056. Add a zone, enter the Pi camera's actual private LAN
address, save/connect, and draw an area over original camera frames. Workspace
configuration is stored by the backend under ignored playground/data/application.
The approved simulated prototype stays separate on port 5070.

This checkpoint has real camera connection and preview only. SAM monitoring,
transport outputs, Meta helper calls and complex rules are not connected yet.
No synthetic detections or performance values are used by the working app.
Existing camera/photo tools on 5051 and bridge on 5055 are unchanged.
