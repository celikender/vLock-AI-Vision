# vLock-AI Vision - Meta Global AI Developer Hackathon 2026

A standalone industrial vision and supervisory vLock application for SCADA developers and manufacturers, designed for integration with existing SCADA systems or independent operation.

**Status:** the working application (port 5056) monitors a camera zone with SAM 3.1, lets Muse Spark configure it from plain language, and publishes status over OPC UA, MQTT and REST. Every zone publishes the same [fixed SCADA tags](ignition/ZONE_TAGS.md).

- **Scope today:** one camera and one monitoring job at a time, at most two objects per zone. Multi-camera is future work.
- **SAM 3.1 engines:** local GPU, Meta Model API image, or Meta Model API video, chosen on the app's Setup page.
- **Status only:** the app sends no machine commands. Treat Unknown or Bad quality as stop; latch and reset belong to the [SCADA integrator](ignition/INTEGRATION.md).

Start here: [overview](docs/project/OVERVIEW.md) · [install guide](docs/install/INSTALL.md) · [connect Ignition](ignition/INTEGRATION.md) · [all documentation](docs/README.md)

## Tested

Measured results are in [test results](docs/testing/TEST_RESULTS.md), and failure behavior is in [edge cases](docs/testing/EDGE_CASES.md).

- **Live:** Pi camera, all three SAM engines, Muse Spark, status read over OPC UA by a separate client, a two-object rule, an unreachable API address giving Unknown, and local worker crash recovery.
- **Earlier experiment only:** detection to a real printer Pause through Ignition, on an older tag path.
- **Not verified:** the tag import and latch in real Ignition, the watchdog in a real gateway, the full chain to a machine, a real Pi unplug and internet cut, a safety vest phrase, the Meta engines in Docker, RTSP cameras, a second PC, and long runs.

## Vision

Connect a camera, describe a monitoring requirement, review the proposed zone and rule, and map equipment signals through documented integration endpoints. The application runs on its own web server, outside Ignition Perspective. Conveyor belts and glass cutters are example configurations, not separate products.

## Planned architecture

```text
Camera / recorded video
        |
SAM 3.1 perception <--- Muse configuration workflow
        |                       |
Deterministic event engine <--- Engineer-approved configuration
        |
Standalone vLock logic and event history
        |
Documented API / industrial adapter
        |
Ignition or another SCADA -> machine simulator
```

Two service boundaries (vision and vLock) will be developed independently and connected into one product with a shared web UI. Final deployment topology will follow measured requirements.

## Development phases

1. Learn and validate SAM 3.1 and Muse in experiments (done; retired playground in Git history).
2. Develop the standalone vLock application and integration contract.
3. Connect both services into one application.
4. Test model limitations, state logic, communication, and recovery.
5. Record a three-minute working demonstration.
6. Publish installation instructions and submit the project.

See [the plan](docs/project/PLAN.md), [integration guide](docs/development/INTEGRATION_PLAN.md), and [development log](docs/development/DEVELOPMENT_LOG.md).

## Structure

- `Start vLock.cmd`: double-click to start the application and its SAM worker.
- `web/`: application server (port 5056) and browser UI.
- `services/vision/`: camera, SAM 3.1 worker and supervisor, Muse assistant, monitoring and zone rules.
- `services/vlock/`: observation store, heartbeat, REST output and OPC UA/MQTT adapters.
- `ignition/`: Ignition package: tag export, tag contract ([INTEGRATION.md](ignition/INTEGRATION.md)) and an example stop latch.
- `demo_site/`: not part of the product. The Pi camera, printer and Ignition project that stand in for a plant in the demo.
- `docs/`: [overview and roadmap, install, test results and edge cases, development records](docs/README.md).
- `playground/`: retired experiments; the application does not use it.

## Existing work and new contributions

[vLock Digital LOTO](https://github.com/celikender/vLock-Digital-LOTO) is Ender Celik's pre-existing Ignition Perspective demonstration. It is background work; no existing implementation has been copied into this repository. New standalone services, AI workflows, integrations, and UI will be identified through actual commits and the development log.

Worker-applied locks and AI-generated supervisory inhibits are separate conditions. Clearing an AI event must not release a worker lock or automatically restart equipment. Demonstrations use simulated or isolated equipment. This project does not replace physical LOTO or safety-rated controls.

## Reproducibility and progress

See [Python setup](docs/install/SETUP.md) and [SAM runtime](docs/install/SAM_RUNTIME.md) for dependency versions and run commands. Never commit API keys, private footage, machine credentials, or generated model files.

Use meaningful commits for completed steps and update the development log with evidence and limitations. Do not present planned features as working features.

## Hackathon

Theme: Push the Frontier. Deadline: November 4, 2026, 9 PM Eastern. Planned submission: public repository and three-minute demo of work built during the event.

Official resources:
- [Participant event details](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)
- [SAM documentation](https://dev.meta.ai/docs/sam/overview)
- [Muse Spark](https://dev.meta.ai/models/muse-spark)



## Run the application

First time? Follow the [install guide](docs/install/INSTALL.md). Then double-click **`Start vLock.cmd`** in the project folder. One window opens and the
browser goes to http://localhost:5056. The app starts the SAM 3.1 worker in Ubuntu/WSL
by itself and preloads the model (about 1–2 minutes on first start; the zone header
shows SAM status). Close that window to stop the app and its SAM worker.

With Docker (NVIDIA GPU, an approved Hugging Face token in `.env`): `docker compose up -d --build`,
then open http://localhost:5056. The app and the SAM 3.1 worker run in separate containers;
the weights are downloaded once with your own token. See [Docker](docs/install/DOCKER.md).

Same thing from a terminal in the project folder:

```powershell
.\.venv\Scripts\python.exe web/application.py --open
```

### Run with the Meta Model API (no GPU)

1. Start the application as above.
2. On the **Setup** page, save your Meta API key, click **Test saved key**, and choose a Meta engine.
3. Restart the application. No SAM worker starts.

| Engine (`VLOCK_SAM_BACKEND`) | Each check, per object | Request limit |
|---|---|---|
| `meta_api` | One frame, about once a second | 3 seconds (`VLOCK_SAM_TIMEOUT_MS`) |
| `meta_api_video` | A four-frame clip, tracking objects | At least 6 seconds |

A timeout, Meta error or lost connection makes the zone Unknown, never Clear. Rules, zone tags and OPC UA do not change.

- **Privacy:** camera frames leave this PC and go to Meta.
- **Cost:** at Meta's listed prices, up to about $9 an hour per object for `meta_api` and about $14 for `meta_api_video` while
  monitoring runs. Requests, latency and scores are logged in `data/application/sam_latency.csv`.
- **Phrases:** Meta advises one simple noun phrase per request, so prefer `person` and `flag` as
  two objects. Two objects only means both are in the area, not that one is holding or wearing
  the other.
- **Not tested with this backend:** real Ignition, Docker, RTSP cameras, long runs and real plant
  footage. Also untested: a safety vest phrase and the heartbeat watchdog in a real gateway.

In a zone: connect the Pi camera, describe what to watch, click **Configure with Muse**,
review the proposal and click **Use this configuration**, then **Enable monitoring**.
For SCADA, enable the OPC UA server (or MQTT) under Integrations and click Save workspace;
SCADA tags lists the fixed zone tags and downloads the Ignition UDT.
See the [application guide](web/app/README.md), [fixed zone tags](ignition/ZONE_TAGS.md),
[Pi installation](demo_site/pi_camera/README.md) and [SAM runtime setup](docs/install/SAM_RUNTIME.md).

This repository is the active source of truth: https://github.com/celikender/vLock-AI-Vision.
Open `vLock-AI-Vision.code-workspace` or the project folder in VS Code.
