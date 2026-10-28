# Main camera UI

Run on the PC with Python 3.10 or newer (no additional packages):

```powershell
python web/server.py
```

Open http://localhost:5051. Enter the Pi LAN IPv4 address (for example
192.168.1.50 or 192.168.1.50:8080), then Connect. Both devices must be on the
same network. The Pi needs the existing playground camera service installed.
Capture photo saves the displayed original JPEG for download. Disconnect ends
PC frame requests; the Pi service continues capturing.

The local backend relays one JPEG per request without re-encoding. The browser
has at most one frame request in flight and targets at most 20 FPS. Frames are
not queued for model processing. Network failures clear the preview and retry.
Request+decode timing includes the relay; Pi frame age is not sensor latency.
Model processing and automatic camera discovery are not implemented.

The server binds only to localhost. Camera targets must be private LAN IPv4
addresses; hostnames, redirects and public IP addresses are not accepted.

On the Pi, confirm boot startup:

```bash
systemctl is-enabled vlock-playground-camera
systemctl status vlock-playground-camera
```

If needed: `sudo systemctl enable --now vlock-playground-camera`.