# Product direction notes

Owner's planning notes, October 30, 2026. These describe intended directions;
they are not a claim that all features below are implemented.

## Current learning setup

We use Ignition by Inductive Automation, specifically Ignition Perspective,
as the SCADA interface. An independent local MQTT bridge connects the Bambu Lab
P1S printer to Ignition through HTTP and Memory Tags.

The owner has verified live printer data and stopping a real print from SCADA.
This provides a small physical integration exercise before industrial work.
A consumer 3D printer does not reproduce an industrial test environment or
establish industrial reliability, recognition accuracy, or safety performance.

## Optional direction: independent printer application

The MQTT bridge can become the foundation of a separate 3D-printer monitoring
and control application with its own interface, independent of Ignition Perspective.
That application could expose temperatures, machine and connection states, and
Pause/Resume/Stop through the same device adapter.

The existing bridge already runs outside Ignition; the independent printer UI
and product packaging are future work. This is an optional development direction,
separate from the immediate vLock milestone. It does not require rebuilding the
working printer connection now.

## Main direction: vLock with two integration paths

Build one independent application core with camera sources, vision observations,
deterministic rules, supervisory vLock state, event history, and documented APIs.
Support two ways to use that core:

| User | Intended experience |
| --- | --- |
| SCADA developer, initially using Ignition | Add adapters, tag mappings and reference screens to integrate camera vision into an existing automation workflow. |
| Manufacturer without a SCADA platform | Use the application's own interface and supported equipment adapters without needing an Ignition installation. |

Candidate use cases include visual monitoring, safety observations and audit
evidence, and quality control. Each use case needs its own validation. Visual
audit evidence and supervisory inhibits do not establish certified machine
protection or replace physical lockout procedures.

Keep perception separate from deterministic control decisions. Preserve worker
locks independently from AI inhibits; missing or stale observations are Unknown,
not Clear. Clearing a vision event must not release a worker lock or automatically
restart equipment. The standalone experience needs these same state semantics.

## Guided setup, documentation and RAG

Make installation and configuration accessible through a guided workflow:

1. The user describes the monitoring task in plain language.
2. The application asks for required camera, machine, network and workflow details.
3. Retrieval-augmented generation (RAG) retrieves relevant, versioned setup guides,
   supported adapter instructions and troubleshooting information.
4. A wizard guides installation, connection checks, camera setup and rule review.
5. The user previews detections and events, verifies equipment mappings, tests
   disconnect/fallback behavior, and reviews the configuration before activation.

Aim to help nontechnical users complete supported setup paths with understandable
questions and clear recovery steps. RAG supplies grounded instructions; it does
not make arbitrary generated configurations or machine commands trustworthy.
Unsupported equipment and tasks must be identified explicitly, with engineering
help requested where needed. Fully automatic setup for any factory is not a
current capability or a promise.

## Development order

1. Preserve the working printer/SCADA experiment and document actual test evidence.
2. Develop standalone vLock and its state/command contract.
3. Connect SAM 3.1 observations to vLock.
4. Connect vLock to SCADA and test the whole workflow on the isolated setup.
5. Test edge cases, fallbacks, stale data, restart recovery and command outcomes.
6. Package reusable adapters, standalone operation, installation guides and guided setup.
7. Explore a separate printer application when it supports the main priorities.

The initial validated workflow should come before a broad setup assistant.

## Git organization

Keep these notes and completed development milestones on `main`. Use a temporary
feature branch when implementing a distinct change, for example
`feature/standalone-printer-ui`. A branch is a workspace for reviewing a change,
not the permanent boundary between two products.

Keep shared adapters and application boundaries in the folder/API structure.
If the printer application later needs its own releases and maintenance, decide
then whether it merits a separate package or repository. No branch or repository
split is required just to record this direction.

See [the development plan](PLAN.md) and [the SCADA experiment](../playground/scada/README.md)
for the current sequence and implemented evidence.
