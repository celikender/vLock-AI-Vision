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

Status: baselines and camera/workspace checkpoint published (dab50c7). Local SAM
monitoring service and explicit enable/stop routes implemented; 18 promoted
regressions and nine application tests pass. Live hardware validation is pending.
Observation-store/output wiring is next. Subsequent checkpoints stay local until
the owner chooses to push the next chapter.
