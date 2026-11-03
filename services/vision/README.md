# Vision service

The first working boundary is `camera.py`: validated private-LAN Pi HTTP targets,
bounded original JPEGs, dimensions/freshness checks and a single latest-frame
buffer. `services/application.py` owns workspace persistence and camera lifecycle.
Run the working UI with `python web/application.py` on port 5056.

The validated monitoring implementation is now available as `monitoring.py`,
with production-relative geometry, configuration, mask and video-transport
modules. It calls the existing local worker on 5052; it does not load a second
model runtime. The working app serializes active zones to one local SAM stream.
No inference starts from camera preview alone. Inference starts only through an
explicit enable request. Stop immediately invalidates the observation and
discards in-flight results; restart requires reconnection/configuration/enable.

The original playground copies are preserved independently. Eighteen promoted
regression checks and nine application checks cover the production boundary.
These use synthetic results and do not establish live hardware inference.
Remote protocols, assisted configuration, combined concepts and interactive
SAM selection remain unwired and are rejected where relevant.

## Worker, Muse and area outlines

- `sam_worker.py`: the local SAM 3.1 worker, promoted from the playground with the
  same routes and protocol plus `/segment/regions` (mask outlines as polygons, via
  OpenCV in the worker environment) and `--preload` (load and warm the model at start).
- `worker_process.py`: starts the worker in Ubuntu/WSL from the project root, watches
  `/health`, reuses an existing worker, never stops an unidentified program, and
  stops only a worker it started.
- `assistant.py`: Muse Spark rule proposals with a JSON-schema response, strict
  validation and an area choice that SAM turns into a polygon (`transport.segment_regions`).
