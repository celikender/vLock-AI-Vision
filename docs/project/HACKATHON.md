# vLock-AI Vision: Meta Global AI Developer Hackathon 2026

**Theme:** Push the Frontier

**Tell your SCADA what to watch in plain English, with no vision engineer and no model training.**

**Demo video:** link coming soon

**Repository:** https://github.com/celikender/vLock-AI-Vision

## The problem

Factories already have cameras and SCADA systems, but connecting them usually takes custom vision work for every scene. Each new object or area goes back to a specialist. And a detector alone isn't enough for a plant: SCADA has to know when a result is old or missing, so that a broken camera is never mistaken for a clear area.

## The solution

A person describes a rule in plain language. Muse Spark proposes it, SAM 3.1 outlines the area, and a person approves it. SAM 3.1 then watches the camera, fixed code applies the rule, and SCADA reads `Active`, `Clear` or `Unknown` through the same tags for every zone.

**vLock tells SCADA what it sees. SCADA decides what the machine does.**

## How it uses Meta's models

| Model | What it does here | How it pushes the frontier |
|---|---|---|
| **Muse Spark** | Turns plain language into a proposed rule, using site notes that include measured results from this camera. It can also run optional advisory frame checks | A SCADA developer can configure vision by describing the job |
| **SAM 3.1** | Finds, outlines and tracks the objects named in the rule | Any object you can name, with no training step, feeding a real industrial control system |

SAM 3.1 runs three ways, chosen on the Setup page: a local GPU, the Meta Model API with images, or the Meta Model API with video. All three feed the same rule code.

## Proven end to end

Tested on November 4, 2026 with a Raspberry Pi camera, real Inductive Automation Ignition and a real Bambu Lab P1S 3D printer. These were observed by hand, so no times were measured.

| Scene | Rule: person AND dog | SCADA |
|---|---|---|
| Person alone | `Clear` | No stop |
| Person holding a real dog | `Active` | Stop latched, printer stopped |
| Camera disabled | `Unknown` | Treated as a stop, printer stopped |

This worked on both the local GPU and Meta's cloud. The app only published status: the stop itself came from the demo's SCADA side, as it would in a real plant.

## Measured

| SAM engine | Time per check | Cost while monitoring, per object |
|---|---|---|
| Local GPU (RTX 3070 Ti Laptop), 4 frames | 3.0-3.9 s | No per-use charge |
| Meta image, 1 frame | About 0.75 s on average | Up to about $9 an hour |
| Meta video, 4 frames | About 1.8 s on average | About $14 an hour |

Small samples from one camera and one room. Full details: [test results](../testing/TEST_RESULTS.md) and [edge cases](../testing/EDGE_CASES.md).

## Screenshots

To be added.

## Limits

This is a working prototype for supervisory monitoring. It is not a fast safety stop, and it **does not replace physical lockout/tagout or safety-rated controls**. It handles one camera and one monitoring job at a time. Accuracy has only been sampled, not benchmarked. Muse's proposals need review and more detailed testing: in one test it got the rule right but left the output type on `event`, and `condition` was chosen by hand. Switching the SAM engine needs an app restart.

## Built during the event

The application, its SAM and Muse integration, the SCADA outputs and the tag contract were built during the event, and the [commits](https://github.com/celikender/vLock-AI-Vision/commits/main) and [development log](../development/DEVELOPMENT_LOG.md) show how. [vLock Digital LOTO](https://github.com/celikender/vLock-Digital-LOTO) is Ender Celik's pre-existing Ignition Perspective demonstration. It is background work, and no implementation was copied from it.

## What's next

More than one camera, the worker-lock lifecycle, an accuracy benchmark on plant footage, long-duration runs, edge and cloud GPU deployment, and a one-step installer.
