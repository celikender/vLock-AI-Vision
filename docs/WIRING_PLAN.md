# Application wiring checkpoints

Approved direction: keep the reviewed UI prototype under playground/combined_app
and build the working application under web/app with runtime code in services/.
Use the existing Pi camera and local SAM windowed-inference path. Publish
observations only; machine actions, worker locks and SCADA latches remain external.

## Baselines on main

- 84765f1: experimental OPC UA client option, isolated transport tests passing.
- 769a0e9: approved Zones UI, simulated only.

## Incremental implementation

1. Camera and workspace: server-owned configuration, private-LAN camera validation,
   original JPEG relay, real connection status and restart-safe disabled state.
2. Monitoring: validated production service boundaries around the tested four-frame
   local SAM transport, polygon geometry, freshness and persistence. No cloud
   fallback or prompt interpretation. Unsupported combinations are rejected.
3. Observation outputs: durable current values/events, five recent events with
   bounded history, known/unknown validity, versioned API, shared optional adapters.
4. Integration evidence: isolated end-to-end tests, live camera checks when reachable,
   hardware/model testing reported separately, exact start commands and limitations.

Each completed checkpoint gets a descriptive local commit after appropriate tests
and staged publication checks. Push chapter by chapter, following owner review.
Keep main as instructed. Preserve existing playground
services and user data. A real UI never displays synthetic detection or latency
fixtures as measured results. Starting inference or enabling a transport is explicit.

## Deferred capabilities

Meta assistant calls, object point/box selection, arbitrary free-text programs,
multi-concept AND/OR evaluation, remote deployment/authentication, native Gateway
packaging and hosted MQTT broker installation need separate implementation and
validation. Their prototype screens are not evidence of working services.

## Compatibility requirements

Preserve working SAM inference, monitoring rules, state management and SCADA
integrations. Adapt the UI to the existing service contracts. Refactoring must
preserve behavior, with incremental compatibility checks. The original playground
is a working reference and remains unchanged. Promoted production copies use
package-relative imports and regression tests; they do not change the model
runtime or its request protocol. Backend services remain authoritative. No
detection or state-decision logic is duplicated into the frontend.

Status: approved UI and camera/workspace checkpoint published (dab50c7). Local
commit 703deb1 wires local SAM monitoring. Durable local observation publication
and read-only REST are implemented next, with 48 production checks passing.
The preserved web suite (25 tests) and monitoring playground (24) also pass.
Live camera check to the saved Pi address did not obtain a fresh JPEG, and the
existing local worker was not reachable. Hardware/model validation remains pending.
External OPC UA/MQTT adapter activation is the next chapter; existing bridge
functionality stays usable independently. Further commits remain local.
