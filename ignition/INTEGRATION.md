# Connecting vLock-AI Vision to Ignition

vLock-AI Vision publishes status. It sends no machine commands and keeps no stop latch. What a
status does to a machine is decided in the SCADA system.

**Treat Unknown or Bad quality as stop; latch/reset is integrator responsibility.**

This product does not replace physical lockout/tagout or safety-rated controls.

## In this folder

| File | What it is |
|---|---|
| `vlock-zones.json` | Ignition tag import: the `vLockZone` UDT, one sample instance (`A-101`) and the heartbeat tags. For your own zones, use **SCADA tags → Download Ignition UDT** in the app. |
| `stop_latch_example.py` | **Example only.** A Gateway timer script showing one way to apply the rule above. Review and adapt it; it is not a safety function. |
| `test_ignition_package.py` | Checks the example's logic and that the export matches the app's generator. |

## Connect

1. In the app: Integrations → enable OPC UA → Save workspace. Save a zone's rule to give it a tag key.
2. In the Gateway, add an OPC UA connection named `vLock Bridge`. On the same PC, use
   `opc.tcp://127.0.0.1:4845/vlock/` with Security None and Anonymous. For another PC, see
   [fixed zone tags](../integrations/ignition/ZONE_TAGS.md).
3. In the Designer: Tag Browser → Import Tags → the exported file.

Tags appear as `[default]vLock/<tag key>/<tag>`. The OPC UA node is
`nsu=urn:vlock:bridge:v1;s=Bridge/Zones/<tag key>/<tag>`. All nodes are read-only.

## Tag contract

The full tag list is in [fixed zone tags](../integrations/ignition/ZONE_TAGS.md). These decide a stop:

### `State`

| Value | Meaning | `Active` | `Quality` |
|---|---|---|---|
| `Active` | The zone rule is met on a fresh, confirmed observation. | True | `Good` |
| `Clear` | The zone rule is not met on a fresh, confirmed observation. | False | `Good` |
| `Valid` | Count zones only: `Count1` and `Count2` are current. There is no condition. | Bad | `Good` |
| `Unknown` | No current result. It never means clear. | Bad | `Unknown` or `Stale` |

`Unknown` includes monitoring being off, the two checks needed to confirm a state after starting,
and any failure. `Reason` says why, for people and logs. Do not build logic on its wording.

| `Reason` | Cause |
|---|---|
| `Camera unavailable. Check the camera connection.` | The camera gave no fresh frame. |
| `Meta SAM unavailable. Check the internet connection and the API key.` | A Meta Model API request timed out, failed or could not be read. |
| `Local SAM unavailable. Check the GPU worker.` | The local GPU worker failed. |

### Two kinds of quality

- **The tag's OPC quality** is set by Ignition. Bad means the value cannot be trusted, for example
  when the app is closed or the OPC connection is down. `Active`, `Count` and `Score` tags also
  carry Bad quality while `State` is `Unknown`.
- **The `Quality` tag** is a string from the app: `Good`, `Unknown` or `Stale`.

During an `Unknown`, `State` itself keeps Good OPC quality with the value `Unknown`. A script that
only checks `Active == True` will therefore miss camera and cloud loss. Read `State`.

### Heartbeat

| Tag | Meaning |
|---|---|
| `vLock/Bridge/HeartbeatCounter` | Goes up about once a second while the app is healthy. |
| `vLock/Bridge/Online` | False when the app's own heartbeat has stopped for 5 seconds. |
| `vLock/Bridge/Status`, `vLock/Bridge/Heartbeat` | Bridge status text and the last heartbeat time. |

A frozen app can leave its last `State` in place, so also watch for a counter that stops moving.
[heartbeat_watchdog.py](../integrations/ignition/heartbeat_watchdog.py) is a reference for this.

## Timing and cost limits

- With `VLOCK_SAM_BACKEND=meta_api`, a check runs about once a second. A state change needs two
  matching checks, so expect a few seconds. It is not a fast safety stop.
- Each Meta request has a 3-second limit per network step. A very slow answer can take longer to fail,
  and an answer past the limit is discarded.
- The app keeps its connection to Meta open. Blocking the name `api.meta.ai` in the hosts file does not
  end that connection, so that method does not simulate a cloud outage. In a simulation, calls kept
  succeeding on the open connection and only a new connection failed. Stop the app's traffic another way.

## Test status

- **Checked on Windows without Ignition:** with `meta_api`, a separate OPC UA client read `State`, `Reason`
  and a moving `HeartbeatCounter`, and an unreachable API address gave `Unknown`. All 26 nodes named in the
  export exist. That client used the namespace index; Ignition reading the `nsu=` paths is untested. The
  separate camera reason has automated tests only.
- **Not tested:** importing this export into real Ignition, the example latch and the heartbeat watchdog in a
  real gateway, the full chain to a machine, a real Pi unplug, a real internet cut, a second PC, long runs.
  The example scripts have only been run outside Ignition with a stand-in for its `system` module.
