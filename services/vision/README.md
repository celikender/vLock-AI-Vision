# Vision service

The first working boundary is `camera.py`: validated private-LAN Pi HTTP targets,
bounded original JPEGs, dimensions/freshness checks and a single latest-frame
buffer. `services/application.py` owns workspace persistence and camera lifecycle.
Run the working UI with `python web/application.py` on port 5056.

The tested SAM monitoring pipeline remains in the playground until the next
wiring checkpoint. No inference is started by camera preview. Remote protocols,
model-assisted configuration and interactive SAM selection remain unwired.
