# Pi USB camera playground

Independent experiment: USB webcam → Pi 5 → browser on PC. Existing local camera
and Claude playground remain available separately. No model calls in this service.

## Install on Pi

Use Raspberry Pi OS with the Pi and PC on the same LAN. Plug in the webcam.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/celikender/vLock-AI-Vision.git
cd vLock-AI-Vision
git checkout main
bash playground/pi_camera/install.sh
```

Open `http://<Pi-IP>:8080` on your PC and click Connect. The installer prints the
Pi IP addresses. Camera capture starts automatically on boot; the page connects
when you click Connect. Capture photo preserves the displayed JPEG without
re-encoding. Disconnect stops browser requests, not the Pi camera service.

## Troubleshooting and tuning

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
journalctl -u vlock-playground-camera -n 50 --no-pager
sudo systemctl stop vlock-playground-camera
python3 playground/pi_camera/server.py --device /dev/video0 --size 640x480 --fps 30
```

The webcam MUST support MJPEG at the requested resolution/frame rate. Choose a
listed mode if defaults fail. For persistent changes use `sudo systemctl edit
vlock-playground-camera`, reset `ExecStart=` then supply the full Python command
with your chosen flags. Restart the service afterward. Prefer a stable
`/dev/v4l/by-id/...` device path when multiple video devices exist.

## Latency design and limits

- FFmpeg copies camera JPEGs; no video decoding/re-encoding on Pi.
- One capture worker continuously drains the webcam and replaces a single latest
  frame, regardless of viewer/model speed. No application frame queue or disk IO.
- Viewer allows one request at a time, targeting at most 20 preview FPS. Slow
  clients skip frames. TCP/browser/camera buffering can still add latency.
- `GET /snapshot.jpg` returns the latest original JPEG for future local/cloud
  processing. `X-Frame-Sequence` lets a consumer skip duplicates. `GET /health`
  reports readiness, sequence, and age since the Pi received the frame.
- Frames older than two seconds return 503. USB failures trigger a capture retry.
- Displayed request+decode time and Pi frame age are diagnostics, NOT measured
  sensor-to-screen latency. Test a visible stopwatch to measure end-to-end delay.
- Start at 640×480. Try 1280×720 only after measuring latency, bandwidth and image
  quality. Ethernet is a useful baseline. Model consumers should request a new
  snapshot when ready rather than queue every preview frame.

This is an unauthenticated trusted-LAN playground; do not port-forward it.
No CORS is enabled: the included page uses the same origin. Later app integration
should fetch snapshots through its backend. No production service files changed.

## Acceptance test on hardware

1. Connect from PC, capture and download an image.
2. Reboot Pi: page reconnects without starting Python manually.
3. Unplug USB: preview reports unavailable; reconnect: preview recovers.
4. Disconnect/reconnect Wi-Fi and confirm recovery.
5. Compare stopwatch delay and CPU use at supported modes before choosing one.

Disable boot capture: `sudo systemctl disable --now vlock-playground-camera`.

Offline tests: `python -m unittest discover -s playground/pi_camera -p 'test_*.py'`.
