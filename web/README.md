# Web application

`web/application.py` serves the working vLock-AI Vision application on
http://localhost:5056, with the browser UI under `web/app/`. Start it with
`Start vLock.cmd` in the project root, or:

```powershell
.\.venv\Scripts\python.exe web/application.py --open
```

Options: `--port`, `--data-dir` (default `data/application`, ignored by Git),
`--no-sam` (do not start the local SAM worker), `--open` (open the browser).
On the first start after the data folder moved, saved zones and history are copied
once from the former `playground/data/application`.

See the [application guide](app/README.md) for camera, Muse, SAM monitoring and
OPC UA/MQTT behavior, and [Pi camera service](../devices/pi_camera/README.md) for
the camera side.

The server binds to localhost only, accepts private-LAN camera addresses only and
rejects cross-site requests. Tests: from `web/`, run
`..\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"`; from the project
root, run `node web/test_zone_workspace.cjs`, `node web/test_camera_preview.cjs` and
`node web/test_analyzed_preview.cjs`.

The earlier camera/photo and monitoring pages on port 5051 were retired with the
playground; they remain in Git history.
