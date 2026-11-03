# Camera source roadmap

## Intended environments

- First: test the camera UI on the development PC.
- Later: run the camera component on Raspberry Pi with USB cameras.
- Support multiple named cameras, including IP and ESP32 cameras.
- Determine each ESP32 camera's available stream from its firmware configuration.

## Current implemented scope

- Pi 5 USB MJPEG capture, boot service, and latest-frame endpoint: devices/pi_camera/.
- Main PC UI: web/, with Pi IP input, connection recovery, preview, and photo capture.
- Owner confirmed the Pi feed and main UI connection work on 2026-10-28.
- Reboot recovery, sustained latency, multiple cameras, and model integration into the main UI still require verification.
- RTSP IP cameras (2026-11-03): choose Camera type **RTSP** in the zone's connection
  settings and enter `rtsp://<private IPv4>[:port]/<path>` plus the username and
  password in their own fields (`services/vision/rtsp.py`). One reader thread decodes
  the stream over TCP with OpenCV/FFmpeg and keeps only the newest frame; a JPEG is
  encoded only when a preview or SAM asks for it, scaled to fit 1280×960 (use the
  camera's sub-stream). The password is written to the local workspace file only and
  is never returned to the browser or written to logs. A lost stream reconnects with
  backoff and the zone shows Unknown meanwhile. Tested with an injected stream and a
  local video file; a real RTSP camera is not yet tested.

## Interface direction for later steps

Represent a source with camera_id, display_name, source_type, and connection
configuration. Source types will include network_stream and usb_device.
Keep source opening/reading behind a camera reader interface. Each active camera
needs its own lifecycle, latest frame, connection state, and bounded buffering.
Associate captures and future model results with camera_id and capture_id.

Do not assume a stable USB numeric index across reboots. Validate device selection
on the target OS. Measure available CPU, memory, bandwidth, decode throughput,
and model round-trip latency before selecting simultaneous camera limits.
A Raspberry Pi camera host does not imply local Muse or SAM inference: decide
where analysis runs separately after measuring the camera pipeline.

The main UI receives Pi frames through its local backend. Multiple-camera controls remain future work.

