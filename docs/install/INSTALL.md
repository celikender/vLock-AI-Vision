# Install guide

## Choose how SAM 3.1 runs

| | Meta Model API | Local GPU | Docker |
|---|---|---|---|
| **Needs a GPU** | No | NVIDIA, 8 GB or more | NVIDIA, 8 GB or more |
| **Camera frames** | Sent to Meta | Stay on this PC | Stay on this PC |
| **Cost** | Per request | None per use | None per use |
| **Hugging Face access** | Not needed | Needed | Needed |
| **Effort** | Least | Most | Medium |

**New here? Start with the Meta Model API.** You can change engines later on the Setup page.

## 1. Install the app (Windows)

You need [Python 3.12](https://www.python.org/downloads/) and [Git](https://git-scm.com/downloads).

```bash
git clone https://github.com/celikender/vLock-AI-Vision.git
```
```bash
cd vLock-AI-Vision
```
```bash
python -m venv .venv
```
```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Start it

Double-click **`Start vLock.cmd`**, or run:

```bash
.\.venv\Scripts\python.exe web/application.py --open
```

The app opens at http://localhost:5056. On the first start, create your admin account.

## 3. Add your settings on the Setup page

Open **Setup** in the sidebar. You don't need to edit any files.

| Setting | Where to get it | Needed for |
|---|---|---|
| Meta API key | Your Meta developer account at [dev.meta.ai](https://dev.meta.ai) | Muse Spark, and the Meta SAM engines |
| SAM engine | Choose from the list | Always. Changing it needs a restart of the app |
| OPC UA username and password | Choose your own | Only when SCADA runs on another PC |
| REST API token | Choose your own | Optional |

Paste the key, click **Save setup**, then click **Test saved key**. This check is free, sends no image and tells you
which models your key can use.

**How keys are kept safe:** they are saved in a `.env` file on the PC running the app. The file is never committed to Git.
The page only shows "Saved" or "Not set", and values are never sent back to the browser or written to the audit log. Only
an admin can open the page. You can also edit `.env` by hand: copy `.env.example` to `.env` and fill it in.

## 4. Run your first zone

1. **Zones → add a zone**, then enter the camera address and click **Connect**.
   - Raspberry Pi USB camera: install the [Pi camera service](../../demo_site/pi_camera/README.md), then use `<Pi address>:8080`.
   - IP camera: choose RTSP and enter its address. RTSP has not yet been tested with a real camera.
2. Describe what to watch and click **Configure with Muse**. Review the proposal and click **Use this configuration**.
3. Click **Enable monitoring**.

**Writing good objects:** use one simple noun per object, such as `person` or `flag`. Bright screens wash out a
camera, so avoid pointing it at them.

## 5. Connect SCADA

Follow the [Ignition guide](../../ignition/INTEGRATION.md). Any OPC UA, MQTT or REST client can read the same status.

The rule for every integrator: treat Unknown or Bad quality as stop; latch and reset are your responsibility.

## Network settings

| What | Where it is | Default |
|---|---|---|
| Web app | This PC only: http://localhost:5056 | Change the port with `--port` |
| Camera | Must be a private network address | |
| OPC UA | **Integrations**: This PC only, or Network with encryption and a login | Port 4845 |
| MQTT | **Integrations** | Off |
| REST | http://localhost:5056/api/v1/zones | Optional token on the Setup page |

For OPC UA in Network mode, also allow its TCP port in Windows Firewall. To reach the web app from another PC you'd need
your own secure tunnel, because the app deliberately refuses other addresses.

## Local GPU engine

1. Request access to [facebook/sam3.1](https://huggingface.co/facebook/sam3.1) on Hugging Face. Meta requires each user to do
   this, so the weights can't be shipped with the app.
2. Set up the worker's environment once: [SAM runtime](SAM_RUNTIME.md).
3. Choose **Local GPU** on the Setup page and restart the app. The first load takes about 1-2 minutes.

## Docker

See [Docker](DOCKER.md). It needs an NVIDIA GPU, and settings are edited in `.env` on the host, so the Setup page is read-only
there. The Meta engines have not been tested in Docker. Because the app container depends on the GPU worker container, a no-GPU
Docker start would need `docker compose up -d --build --no-deps app`, which is also untested.

## Where your data lives

Everything is in `data/application/`, which Git ignores. It does not keep growing:

| File | Limit |
|---|---|
| `observations.sqlite3` (history) | Newest 1,000 events. Measured at about 1.7 MB after 6,000 writes |
| `audit.log` | 5 MB, plus one older file |
| `sam_latency.csv` (Meta engines) | 5 MB, plus one older file |
| `sam_worker.log` (local engine) | 5 MB, plus two older files |
| `zones/<id>/` (settings per zone) | Removed when you delete the zone |

No camera images are saved to disk. At one check a second, 1,000 events cover about 17 minutes of history.

## Updating

```bash
git pull
```
```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Troubleshooting

| You see | Do this |
|---|---|
| `VLOCK_SAM_BACKEND must be ...` and the app won't start | In `.env`, set it to `local`, `meta_api` or `meta_api_video`. A key belongs in `META_API_KEY` |
| "Python environment missing" | Run the commands in step 1 |
| Zone stays `Unknown` | Read its reason: it names the camera, Meta or the local worker |
| "SAM 3.1 is not ready" | Local engine: wait for the first load, or see [SAM runtime](SAM_RUNTIME.md). Meta engines: add the key on the Setup page |
| "Port 5056 is used by another program" | Close the other copy, or start with `--port 5057` |
| Setup page says "Restart needed" | Close the app's window and start it again |
| Test saved key says rejected | Paste the key again and check your Meta account |

## Install test status

- A clean checkout, a fresh virtual environment and the first-run Setup page were tested on the development PC. A separate
  clean PC has not been tried.
- Windows only so far: Linux hosts are untested.
