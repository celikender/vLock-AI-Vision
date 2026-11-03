# vLock-AI Vision - Meta Global AI Developer Hackathon 2026

A standalone industrial vision and supervisory vLock application for SCADA developers and manufacturers, designed for integration with existing SCADA systems or independent operation.

**Development status:** The working application (port 5056) monitors camera zones with local SAM 3.1, lets Muse Spark configure a zone from plain language (rule plus a SAM-outlined area), and publishes observations through local REST, OPC UA and MQTT. Pi 5 camera streaming and the earlier detection-to-printer Pause through Ignition are owner-tested. The [SCADA playground](playground/scada/README.md) connects a real Bambu P1S through MQTT to Ignition Perspective.

Standalone vLock and end-to-end vision-to-SCADA integration are planned. See the [development log](docs/DEVELOPMENT_LOG.md) for verified milestones and limitations.

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

1. Learn and validate SAM 3.1 and Muse in the playground.
2. Develop the standalone vLock application and integration contract.
3. Connect both services into one application.
4. Test model limitations, state logic, communication, and recovery.
5. Record a three-minute working demonstration.
6. Publish installation instructions and submit the project.

See [the plan](docs/PLAN.md), [playground guide](playground/README.md), [integration guide](docs/INTEGRATION.md), and [development log](docs/DEVELOPMENT_LOG.md).

## Structure

- `playground/`: learning experiments and performance/limitation reports.
- `services/vision/`: planned SAM/Muse service.
- `services/vlock/`: planned independent vLock state service.
- `web/`: main PC camera UI with Pi IP address connection, preview, and capture.
- `integrations/ignition/`: planned reference SCADA integration.
- `docs/`: architecture, roadmap, integration contract, and public progress.

## Existing work and new contributions

[vLock Digital LOTO](https://github.com/celikender/vLock-Digital-LOTO) is Ender Celik's pre-existing Ignition Perspective demonstration. It is background work; no existing implementation has been copied into this repository. New standalone services, AI workflows, integrations, and UI will be identified through actual commits and the development log.

Worker-applied locks and AI-generated supervisory inhibits are separate conditions. Clearing an AI event must not release a worker lock or automatically restart equipment. Demonstrations use simulated or isolated equipment. This project does not replace physical LOTO or safety-rated controls.

## Reproducibility and progress

See [Python setup](docs/SETUP.md) and [camera playground](playground/camera/README.md) for dependency versions and run commands. Never commit API keys, private footage, machine credentials, or generated model files.

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

Same thing from a terminal in the project folder:

```powershell
.\.venv\Scripts\python.exe web/application.py --open
```

In a zone: connect the Pi camera, describe what to watch, click **Configure with Muse**,
review the proposal and click **Use this configuration**, then **Enable monitoring**.
For SCADA, enable the OPC UA server under Integrations and click Save workspace.
See the [application guide](web/app/README.md), [Pi installation](playground/pi_camera/README.md)
and [SAM runtime setup](playground/segmentation/README.md).

This repository is the active source of truth: https://github.com/celikender/vLock-AI-Vision.
Open `vLock-AI-Vision.code-workspace` or the project folder in VS Code.
