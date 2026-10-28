# Camera source roadmap

## Intended environments

- First: test the camera UI on the development PC.
- Later: run the camera component on Raspberry Pi with USB cameras.
- Support multiple named cameras, including IP and ESP32 cameras.
- Determine each ESP32 camera's available stream from its firmware configuration.

## Current implemented scope

- Browser-local camera and Claude photo experiments: playground/camera/.
- Pi 5 USB MJPEG capture, boot service, and latest-frame endpoint: playground/pi_camera/.
- Main PC UI: web/, with Pi IP input, connection recovery, preview, and photo capture.
- Owner confirmed the Pi feed and main UI connection work on 2026-10-28.
- Reboot recovery, sustained latency, multiple cameras, and model integration into the main UI still require verification.

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

The main UI receives Pi frames through its local backend. The separate playground retains browser-local camera access. Multiple-camera controls remain future work.

