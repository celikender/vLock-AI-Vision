# vLock-AI Vision - Meta Global AI Developer Hackathon 2026

A standalone industrial vision and supervisory vLock application for SCADA developers and manufacturers, designed for integration with existing SCADA systems or independent operation.

**Development status:** The working application (port 5056) monitors camera zones with local SAM 3.1 (one or two objects per zone), lets Muse Spark configure a zone from plain language (rule plus a SAM-outlined area), and publishes observations through REST, OPC UA and MQTT. Every zone publishes the same [fixed SCADA tags](integrations/ignition/ZONE_TAGS.md) with an Ignition UDT download; OPC UA serves this PC only, or the plant network with encryption and a login.

- Owner-tested: Pi 5 camera streaming and the earlier detection-to-printer Pause through Ignition (bridge experiment). The [Bambu P1S project](integrations/ignition/p1s_printer/README.md) connects a real printer to Ignition Perspective through a local connector.
- Tested by automated and live local checks, not yet in the owner's Ignition: the fixed zone tags and OPC UA network access. Not yet tested anywhere: the UDT import into Ignition, access from a second PC, and a positive two-object detection on the live camera.
- Planned: the standalone vLock worker-lock lifecycle (separate from AI inhibits) and multi-zone monitoring on one GPU.

See the [development log](docs/DEVELOPMENT_LOG.md) for verified milestones and limitations.

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

See [the plan](docs/PLAN.md), [integration guide](docs/INTEGRATION.md), and [development log](docs/DEVELOPMENT_LOG.md).

## Structure

- `Start vLock.cmd`: double-click to start the application and its SAM worker.
- `web/`: application server (port 5056) and browser UI.
- `services/vision/`: camera, SAM 3.1 worker and supervisor, Muse assistant, monitoring and zone rules.
- `services/vlock/`: observation store, heartbeat, REST output and OPC UA/MQTT adapters.
- `devices/pi_camera/`: Raspberry Pi 5 USB camera service and installer.
- `integrations/ignition/`: Ignition reference integration and the Bambu P1S Perspective project.
- `docs/`: plan, setup, SAM runtime, integration contract, reports and development log.
- `playground/`: retired experiments; the application does not use it.

## Existing work and new contributions

[vLock Digital LOTO](https://github.com/celikender/vLock-Digital-LOTO) is Ender Celik's pre-existing Ignition Perspective demonstration. It is background work; no existing implementation has been copied into this repository. New standalone services, AI workflows, integrations, and UI will be identified through actual commits and the development log.

Worker-applied locks and AI-generated supervisory inhibits are separate conditions. Clearing an AI event must not release a worker lock or automatically restart equipment. Demonstrations use simulated or isolated equipment. This project does not replace physical LOTO or safety-rated controls.

## Reproducibility and progress

See [Python setup](docs/SETUP.md) and [SAM runtime](docs/SAM_RUNTIME.md) for dependency versions and run commands. Never commit API keys, private footage, machine credentials, or generated model files.

Use meaningful commits for completed steps and update the development log with evidence and limitations. Do not present planned features as working features.

## Hackathon

Theme: Push the Frontier. Deadline: November 4, 2026, 9 PM Eastern. Planned submission: public repository and three-minute demo of work built during the event.

Official resources:
- [Participant event details](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)
- [SAM documentation](https://dev.meta.ai/docs/sam/overview)
- [Muse Spark](https://dev.meta.ai/models/muse-spark)



## Run the application

Double-click **`Start vLock.cmd`** in the project folder. One window opens and the
browser goes to http://localhost:5056. The app starts the SAM 3.1 worker in Ubuntu/WSL
by itself and preloads the model (about 1–2 minutes on first start; the zone header
shows SAM status). Close that window to stop the app and its SAM worker.

With Docker (NVIDIA GPU, an approved Hugging Face token in `.env`): `docker compose up -d --build`,
then open http://localhost:5056. The app and the SAM 3.1 worker run in separate containers;
the weights are downloaded once with your own token. See [Docker](docs/DOCKER.md).

Same thing from a terminal in the project folder:

```powershell
.\.venv\Scripts\python.exe web/application.py --open
```

In a zone: connect the Pi camera, describe what to watch, click **Configure with Muse**,
review the proposal and click **Use this configuration**, then **Enable monitoring**.
For SCADA, enable the OPC UA server (or MQTT) under Integrations and click Save workspace;
SCADA tags lists the fixed zone tags and downloads the Ignition UDT.
See the [application guide](web/app/README.md), [fixed zone tags](integrations/ignition/ZONE_TAGS.md),
[Pi installation](devices/pi_camera/README.md) and [SAM runtime setup](docs/SAM_RUNTIME.md).

This repository is the active source of truth: https://github.com/celikender/vLock-AI-Vision.
Open `vLock-AI-Vision.code-workspace` or the project folder in VS Code.
