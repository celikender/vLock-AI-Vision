# vLock-AI Vision

**Tell your SCADA what to watch in plain English, with no vision engineer and no model training.**

vLock-AI Vision connects a camera to an existing SCADA system. You describe a rule in plain language, Muse Spark proposes it, you approve it, SAM 3.1 watches the camera, and SCADA reads the result through fixed tags.

Built for the [Meta Global AI Developer Hackathon 2026](docs/project/HACKATHON.md).

**Demo video:** link coming soon.

## The problem

Plants already have cameras and SCADA systems, but connecting one to the other usually means custom vision work for every scene. Each new object, area or rule goes back to a specialist. SCADA also needs more than a detection: it has to know when a result is old or missing, so that a broken camera is never mistaken for a clear area.

## What it does

1. **Connect a camera:** Raspberry Pi USB, HTTP or RTSP.
2. **Describe the rule:** "Alert when a person and a dog are both in the area for one second."
3. **Review it:** Muse Spark proposes the rule and SAM 3.1 outlines the area. Nothing runs until a person approves it.
4. **Monitor:** SAM 3.1 checks the camera, and fixed code applies the approved rule.
5. **Publish:** SCADA reads the same tags for every zone over OPC UA, MQTT or REST. Ignition users can download a ready-made UDT.

| `State` | Meaning |
|---|---|
| `Active` | The rule is met on a fresh, confirmed observation |
| `Clear` | The rule is not met on a fresh, confirmed observation |
| `Unknown` | No current result, for example a lost camera or failed model call. **It never means clear** |
| `Valid` | Count zones only: the counts are current |

**vLock tells SCADA what it sees. SCADA decides what the machine does.** The app sends no machine commands. Integrators should treat Unknown or Bad quality as stop, and latching and reset are theirs to own. See the [Ignition guide](ignition/INTEGRATION.md).

## Tools

| Purpose | Tools |
|---|---|
| Meta models | **Muse Spark** (`muse-spark-1.3`) for rule proposals and optional advisory frame checks; **SAM 3.1** for segmentation and tracking |
| SAM 3.1 engines | Local NVIDIA GPU with PyTorch in Ubuntu/WSL and weights from Hugging Face, or the Meta Model API for image or video |
| Application | Python, a browser UI in plain JavaScript, SQLite, OpenCV and Pillow, `meta-sam-parser` |
| SCADA outputs | OPC UA (`asyncua`), MQTT (`paho-mqtt`), REST |
| Deployment | Windows launcher, or Docker with separate app and GPU containers |
| Demo site | Inductive Automation Ignition with Perspective, Raspberry Pi 5 with a USB camera, Bambu Lab P1S printer through a local MQTT connector |

## Architecture

```text
 Camera (Pi USB, HTTP, RTSP)
        |  latest frame only, no queue
        v
+------------------- vLock-AI Vision ------------------+        +---------------------+
|                                                      |        |  SAM 3.1, one of:   |
|  Web UI, logins, audit log, Setup page               |        |  - local GPU worker |
|                                                      | frames |  - Meta image API   |
|  Monitoring  ----------------------------------------+------->|  - Meta video API   |
|     |                                                |<-------+                     |
|     v                                                | masks  +---------------------+
|  Fixed rule code <-- rule a person approved          |
|     |                     ^                          |        +---------------------+
|     |                     +--------------------------+<-------+  Muse Spark         |
|     v                                                |proposal|  writes the rule    |
|  Observation store: freshness, Unknown, history      |        +---------------------+
|     |                                                |
|     v                                                |
|  Fixed tags: OPC UA, MQTT, REST, heartbeat           |
+-----+------------------------------------------------+
      |  status only: no machine commands
      v
 SCADA (Ignition): latch, reset and machine logic --> machine
```

Why it's built this way:

- **Muse proposes, code decides.** Models find objects and draft rules. Fixed code decides the state, so results can be explained and repeated. Muse's frame checks are advisory and never change `Active` or `State`.
- **Failures are visible.** A check that is late, lost or unreadable publishes `Unknown` with a reason.
- **Tags don't move.** Changing a rule, object or zone name keeps the same tag path, so a new prompt needs no SCADA changes.
- **The engine is a choice.** All three SAM engines return the same results to the same rule code.
- **Keys stay on the server.** The Setup page saves keys to `.env` on that PC. They are never sent back to the browser or written to the audit log.

| Folder | What it holds |
|---|---|
| `web/` | Application server and browser UI |
| `services/vision/` | Camera, SAM engines, Muse, monitoring and zone rules |
| `services/vlock/` | Observation store, heartbeat and OPC UA, MQTT and REST outputs |
| `ignition/` | SCADA package: tag export, [tag contract](ignition/INTEGRATION.md) and example scripts |
| `skills/` | Notes Muse reads when it proposes a rule |
| `demo_site/` | **Not part of the product:** the Pi camera, printer and Ignition project that stand in for a plant |
| `docs/` | [Overview, install guide, test results and development records](docs/README.md) |
| `playground/` | Retired experiments; the application does not use it |

## Test results

**Full chain, tested by the project owner on November 4, 2026** with a Pi camera, real Ignition and a real 3D printer. These were observed by hand, so no times were measured:

| Test | Result |
|---|---|
| Person alone, with a person AND dog rule | `Clear` |
| Person holding a real dog | `Active`: the SCADA side latched a stop and the printer stopped |
| Camera disabled | `Unknown`: treated as a stop, and the printer stopped |
| Local GPU and Meta cloud engines | Both worked |

**Measured with a small sample, one camera and one room:**

| SAM engine | Time per check | Cost while monitoring, per object |
|---|---|---|
| Local GPU (RTX 3070 Ti Laptop), 4 frames | 3.0-3.9 s | No per-use charge |
| Meta image, 1 frame | 0.4-1.6 s, about 0.75 s on average | Up to about $9 an hour |
| Meta video, 4 frames | 1.2-2.9 s, about 1.8 s on average | About $14 an hour |

**Reliability checks:** crash recovery of the local worker, a daily spending limit that survives a restart, backoff after repeated Meta failures, history held at about 1.7 MB after 6,000 writes, and about 300 automated tests.

**Not verified yet:** detailed testing of Muse's proposals, a real Pi unplug and internet cut, a safety vest phrase, accuracy on plant footage, the Meta engines in Docker, a real RTSP camera, a second PC on OPC UA, Linux hosts, a separate clean PC and long runs.

Details: [test results](docs/testing/TEST_RESULTS.md) · [edge cases](docs/testing/EDGE_CASES.md)

## Limits

- One camera and one monitoring job at a time, with at most two objects per zone, and at most 8 objects of one kind in a frame (6 on Meta video).
- Checks take a second or more and a state change needs two matching observations, so this is supervisory monitoring, not a fast safety stop.
- **It does not replace physical lockout/tagout or safety-rated controls.** Demonstrations use isolated equipment.
- With a Meta engine, camera frames leave your PC and are sent to Meta.
- Switching the SAM engine needs an app restart.
- Always review Muse's proposal. In testing it set up the rule correctly but left the output type on `event`, and `condition` had to be chosen by hand for SCADA to use it as planned. Muse needs more detailed testing.

## What's next

- More than one camera and more than one monitoring job.
- The worker-lock lifecycle, kept separate from AI inhibits.
- A real accuracy benchmark on plant footage, and long-duration runs.
- Edge and cloud GPU deployment.
- A one-step installer.

## Run it

Follow the [install guide](docs/install/INSTALL.md). In short, with Python 3.12 on Windows:

```powershell
git clone https://github.com/celikender/vLock-AI-Vision.git
cd vLock-AI-Vision
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then double-click **`Start vLock.cmd`**. The browser opens http://localhost:5056.

1. Create your admin account.
2. On the **Setup** page, save your Meta API key, click **Test saved key**, and choose a SAM engine. Restart the app if you changed the engine.
3. Add a zone, connect the camera, and click **Configure with Muse**. Review the proposal and click **Use this configuration**.
4. Click **Enable monitoring**.
5. To connect SCADA, follow the [Ignition guide](ignition/INTEGRATION.md).

| Engine (`VLOCK_SAM_BACKEND`) | Needs | Each check, per object |
|---|---|---|
| `local` (default) | NVIDIA GPU, 8 GB or more; approved Hugging Face access; [SAM runtime](docs/install/SAM_RUNTIME.md) | Four frames with tracking |
| `meta_api` | Meta API key | One frame, about once a second |
| `meta_api_video` | Meta API key | A four-frame clip with tracking |

Docker is also available: see [Docker](docs/install/DOCKER.md). A daily spending limit, $10 by default, stops paid requests. It's an estimate, so your Meta account shows the real bill.

## Existing work and new contributions

[vLock Digital LOTO](https://github.com/celikender/vLock-Digital-LOTO) is Ender Celik's pre-existing Ignition Perspective demonstration. It is background work; no existing implementation has been copied into this repository. New work can be seen in the commits and the [development log](docs/development/DEVELOPMENT_LOG.md).

Worker-applied locks and AI-generated supervisory inhibits are separate conditions. Clearing an AI event must not release a worker lock or automatically restart equipment.

Never commit API keys, private footage, machine credentials or model files.
