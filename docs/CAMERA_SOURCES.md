# Camera source roadmap

## Intended environments

- First: test the camera UI on the development PC.
- Later: run the camera component on Raspberry Pi with USB cameras.
- Support multiple named cameras, including IP and ESP32 cameras.
- Determine each ESP32 camera's available stream from its firmware configuration.

## Current implemented scope

The first test is browser-local: start the default PC camera, preview, stop, and
capture one photo. No network stream input or generated feed remains in the UI.
Physical camera behavior needs owner testing. Raspberry Pi USB, multiple cameras,
and IP/ESP32 feeds are future work. The Python server only serves the page.

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

For later Pi feeds, the browser will receive frames from a camera service. The current PC test uses browser-local camera access. Multiple-camera controls follow successful single-camera testing.

