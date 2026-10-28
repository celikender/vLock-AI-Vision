# vLock-AI Vision

A standalone industrial vision and supervisory vLock web application for SCADA developers.

**Status: Pi 5 USB camera streaming and the main PC camera UI are implemented and confirmed working by the owner. Captured-photo Claude analysis exists in the playground. Connecting model services to the main UI is the next step; Muse, SAM, and SCADA integration remain unfinished.**

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



## Main camera app

Run `python web/server.py` on your PC and open http://localhost:5051.
Enter the Pi IP address and click Connect. See [main UI guide](web/README.md)
and [Pi installation](playground/pi_camera/README.md).

This repository is the active source of truth: https://github.com/celikender/vLock-AI-Vision.
Open `vLock-AI-Vision.code-workspace` or the project folder in VS Code.
