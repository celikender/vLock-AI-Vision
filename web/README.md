# Main camera UI

Run on the PC with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r playground/camera/requirements.txt
.\.venv\Scripts\python.exe web/server.py
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
Automatic camera discovery is not implemented. Claude captured-photo analysis is available below.

The server binds only to localhost. Camera targets must be private LAN IPv4
addresses; hostnames, redirects and public IP addresses are not accepted.

On the Pi, confirm boot startup:

```bash
systemctl is-enabled vlock-playground-camera
systemctl status vlock-playground-camera
```

If needed: `sudo systemctl enable --now vlock-playground-camera`.
## Claude photo analysis

Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL in the root local .env. Existing settings
reload on every request; the browser never receives the key.
Connect, Capture photo, enter a prompt, and click Analyze and draw.
Examples: "Draw boxes around my eyes", "Find the cups and count them", or
"Describe the scene and mark the tools". Blank prompts describe and mark main objects.
The original capture remains visible. Text and a separately downloadable annotated
PNG appear below it. Only the selected photo and prompt are sent to Claude.
The live feed continues while analysis runs; captures are disabled during that request.
Annotations are labeled rectangles with approximate coordinates, not SAM masks.
No visible target is a valid answer with no boxes. Verify positioning visually.

The adapter remains in playground/camera/annotations.py while this behavior is tested.
The local server allows one model request at a time and applies image/prompt limits,
same-origin checks, bounded timeouts, and sanitized errors. No automatic paid retries.
Offline tests: run unittest discovery in playground/camera and web separately.

## SAM 3.1 local/cloud experiment

After capturing, use the SAM section to select Local GPU or Cloud API, enter an
object phrase such as monitor, and Segment captured photo. Check setup shows
credential and local-runtime readiness. See [setup instructions](../playground/segmentation/README.md).
Cloud requests send the capture to Meta; local requests stay on the laptop.
