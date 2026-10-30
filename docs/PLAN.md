# Development plan

## Product goal

Enable SCADA developers to integrate visual monitoring and supervisory vLock behavior through a standalone web application with clear endpoints and equipment mappings. Aim for reusable configuration across machines; validate each supported monitoring scenario.

See [product direction notes](PRODUCT_DIRECTION.md) for the intended standalone
and Ignition integration paths, the optional independent printer application,
and future guided installation/documentation with RAG. These are planning notes;
the milestone and validation requirements below still apply.

## Phase 1: SAM 3.1 and Muse

Start with small image experiments, then recorded clips. Verify credentials, model IDs, output formats, prompts, mask geometry, tracking behavior, latency, rate limits, and costs. Muse should interpret intent, invoke perception/validation tools, and propose structured configuration for engineer review. It must not be required for every frame.

Exit evidence: reproducible real inference, saved sanitized examples, measured limitations, and one approved monitoring rule. Treat direct RTSP and near-real-time hosted inference as unverified until tested.

## Phase 2: standalone vLock

Design equipment state, worker-lock lifecycle, independent AI inhibit reasons, explicit release/reset/start behavior, event history, and authenticated integration endpoints. Inspect the old implementation before reusing algorithms. Define durable state ownership and concurrent request handling.

Exit evidence: simulated machine integration demonstrating apply, release, reset, and independent inhibit conditions. Requested stop and confirmed stop are separate states.

## Phase 3: one application

Connect vision events to vLock through a versioned contract. Provide one standalone UI: source setup -> monitoring intent -> review/edit zone and rule -> map equipment -> test -> approve activation -> inspect events and health.

Start with one source, one rule type, and one SCADA connection. Ignition is the reference integration, not the application host. Choose REST first for the contract; add MQTT if it is the most practical event path. OPC UA remains a later option.

## Phase 4: test

Test zone geometry, minimum duration, debounce, event transitions, worker locks versus AI inhibits, idempotent requests, resets, stale state, lost footage, inference failure, transport loss, and restart recovery. Unknown observations must remain distinguishable from a clear zone.

Evaluate person outside/inside zone, machine running/stopped, non-target objects, brief occlusion, and disconnects. Measure request latency separately from footage time and end-to-end publication latency. Clearly label replayed or precomputed outputs.

## Phase 5: demo

Three minutes: problem and setup, natural-language configuration with approval, actual perception and event generation, SCADA response and simulated vLock state, then engineering evidence. Clearly identify pre-existing work and newly built features.

## Phase 6: publish

Verify clean installation, public repository, accessible video, contributor list, implemented/planned distinction, model versions, footage rights, and evaluation evidence. Submit before November 4 at 9 PM Eastern.

## Target milestones

- Oct 27-28: model learning and inference feasibility.
- Oct 29-30: first vision-to-event slice and vLock contract.
- Oct 31-Nov 1: standalone UI and Ignition reference connection.
- Nov 2: integrated testing and feature freeze.
- Nov 3: reproducible setup, documentation, demo recording.
- Nov 4: final verification and submission.

These are targets, not completed work. Reduce secondary features if inference or integration risks consume time.

## Judging evidence

Impact 30%: real automation workflow and users.
Meta tooling 25%: useful collaboration between Muse and SAM.
Technical execution 20%: validated configuration, deterministic logic, robust contracts.
Demo 25%: one clear, complete working workflow.

## Open decisions

Participant track; existing vLock behavior to preserve; Ignition version/modules; endpoint ownership; credentials and authorization; machine-state quality semantics; footage availability; hardware; model budget; exact latency target; final deployment packaging.

## Current checkpoint — 2026-10-28

The owner confirmed Pi 5 USB webcam streaming and the main UI IP-address connection work.
Continue development only in vLock-AI-Vision. Existing phase goals above remain the roadmap.
Next: bring explicit captured-photo analysis into the main UI, configure Meta access,
then validate Muse/SAM using the captured frame. The Anthropic key exists locally;
the Meta key is not configured. Do not treat local configuration as verified API access.
