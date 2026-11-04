# vLock-AI Vision overview

**Tell your SCADA what to watch in plain English, with no vision engineer and no model training.**

Built for the Meta Global AI Developer Hackathon 2026, theme "Push the Frontier".

## The problem

Plants already have cameras and SCADA systems, but connecting one to the other usually takes custom vision
work for every new scene. Each change of object or area means going back to a specialist.

## What it does

1. **Connect a camera:** a Raspberry Pi USB camera, an HTTP camera or an RTSP camera.
2. **Describe the rule:** "Alert when a person and a laptop are both on the desk for one second."
3. **Review:** Muse Spark proposes the rule and SAM 3.1 outlines the area. Nothing runs until a person approves it.
4. **Monitor:** SAM 3.1 checks the camera, and fixed code applies the approved rule.
5. **Publish:** SCADA reads the same fixed tags for every zone over OPC UA, MQTT or REST, with a downloadable
   Ignition UDT.

```text
Camera --> SAM 3.1 (local GPU, or Meta Model API image or video)
                |
                v
      Fixed rule code <-- rule approved by a person <-- Muse Spark proposal
                |
                v
      Fixed SCADA tags over OPC UA, MQTT, REST --> SCADA decides what the machine does
```

## How it uses Meta's models

| Model | Job | When it runs |
|---|---|---|
| **Muse Spark** | Turns plain language into a proposed rule, using notes from the skills folder as reference data | When someone configures a zone; optional advisory frame checks |
| **SAM 3.1** | Finds and outlines the objects named in the rule | Every monitoring check |

Muse never decides a zone's state. Its proposals need approval, and its frame checks are advisory tags that
never change `Active` or `State`.

## Choices that matter in a plant

- **Unknown is never Clear.** A lost camera, a failed model call or an old result publishes `Unknown` with a reason.
- **Status only.** The app sends no machine commands. Latching, reset and stopping belong to the SCADA integrator.
- **Stable tags.** Changing a rule, object or zone name never moves a tag, so bindings keep working.
- **Your choice of engine.** Keep video on your own GPU, or use Meta's API with no GPU at all.
- **Secure by default.** Logins with roles, an audit log, encrypted OPC UA for plant networks, and keys that never reach the browser.
- **It recovers.** The SAM worker restarts after a crash, damaged files are kept aside and replaced, and monitoring never resumes unattended after a restart.

## Measured so far

| SAM engine | Time per check | Cost while monitoring, per object |
|---|---|---|
| Local GPU (RTX 3070 Ti Laptop), 4 frames | 3.0-3.9 s | No per-use charge |
| Meta image, 1 frame | 0.4-1.6 s, about 0.75 s on average | Up to about $9 an hour |
| Meta video, 4 frames | 1.2-2.9 s, about 1.8 s on average | About $14 an hour |

These are small samples from one camera and one room. Details are in the [test results](../testing/TEST_RESULTS.md).

## Limits today

- One camera and one monitoring job at a time, and at most two objects per zone. Multi-camera is future work.
- Checks take a second or more and a state change needs two matching observations, so this is supervisory
  monitoring, not a fast safety stop. It does **not** replace physical lockout/tagout or safety-rated controls.
- The fixed tags have not yet been imported into real Ignition.
- Accuracy has only been sampled, not benchmarked.

See the [edge cases](../testing/EDGE_CASES.md) and the [roadmap](ROADMAP.md).
