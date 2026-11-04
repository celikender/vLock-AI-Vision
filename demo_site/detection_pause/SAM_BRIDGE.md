# SAM observation to Ignition Pause experiment

## Confirmed checkpoint — October 31, 2026

The owner confirmed this live path in Ignition 8.3 Maker Edition / Perspective:

```text
Pi camera -> local SAM 3.1 -> monitoring zone rule -> vLock Bridge HTTP input
          -> bridge OPC UA server -> Ignition Active tag
          -> Gateway Tag Change -> existing printer connector -> P1S Pause
```

Entering the configured zone paused the running printer. The owner estimated
approximately three seconds from entering to pause; this is a subjective live
observation, not an instrumented latency result. Manual Pause was also confirmed.
The printer is home test equipment for a generic observation bridge. SCADA/PLC
owns machine actions, permissives, interlocks and reset. This experimental path
is not a safety-rated protective function.

## Start the application (current setup)

The October 31 checkpoint used the separate playground monitor (5051) and vLock
Bridge (5055). Both are retired. The working application now hosts the same
read-only OPC UA server contract itself:

1. Double-click `Start vLock.cmd`. The app starts the SAM worker by itself.
2. Integrations: enable **OPC UA** in Host server mode, port 4845, then Save workspace.
3. Configure the zone (Muse or manually), save the rule and enable monitoring.

Keep the existing printer connector running; do not start a duplicate service.
The app's asset is the **zone ID** and its source is **vision**, so the Active node
is `Bridge/Assets/<zone id>/Signals/vision/<output>/Active` instead of the bridge's
`conveyor_01/sam/zone_condition` path. Copy the exact NodeId from the app's
**SCADA tags** page and re-point the Ignition OPC tag (or the Tag Change event's
watched path) to it. This re-pointing has not yet been owner-tested. Prefer the
fixed zone tag `Bridge/Zones/<tag key>/Active` ([fixed zone tags](ZONE_TAGS.md)): it
does not change when the output is renamed.

## OPC UA connection and tags

Gateway: Connections > OPC > Connections. Add `vLock Bridge` using
`opc.tcp://127.0.0.1:4845/vlock/`, Anonymous, Security Policy/Mode None and read-only.
This endpoint is for local connections on the same PC. Leave native keep-alive
settings at their initial defaults. The optional bridge HeartbeatPulse is an
application pulse, not evidence that the camera/model has fresh data.

Designer: Tag Browser > Browse Devices > vLock Bridge > vLock > conveyor_01
(with the application: the zone ID folder instead of conveyor_01).
Refresh after SAM publishes its first observation to discover new nodes. Import
the SAM zone condition Active node; existing values update by subscription, but
new nodes need a browse/import. The owner's final mapping is:

| Ignition path | Source / purpose |
| --- | --- |
| `[default]vLockBridge/vLock/conveyor_01/Active` | SAM zone_condition Active, Boolean OPC tag |
| `[default]vLockBridge/PauseRequested` | Boolean Memory tag, initial false; remembers one request |

The Active OPC Item Path is:

```text
nsu=urn:vlock:bridge:v1;s=Bridge/Assets/conveyor_01/Signals/sam/zone_condition/Active
```

The namespace URI avoids assuming a namespace index. Counts are independently
available at `Signals/sam/people_count/NumericValue`: whole-frame detections,
not zone occupancy or cumulative unique visitors. Bad/stale quality means
unavailable, never a confirmed zero or clear. Old manual condition streams may
make the aggregate asset inhibit unknown; this test explicitly watches SAM Active.

`sam_bridge_tags.json` is a minimal additive tag-import example for the default
provider. It includes the final Active/latch paths plus optional count/status
tags. The JSON layout has been checked offline; importing this new file has not
been owner-tested. The owner configured the live tags manually. Back up existing
tags, use collision policy Ignore for existing paths, and compare their OPC paths;
do not overwrite the current latch during a running experiment.

## Gateway event

In the same project as the existing `bambuP1s` library:

1. Open Scripting > Gateway Events > Tag Change. Create `PauseOnDetection`.
2. Watch only `[default]vLockBridge/vLock/conveyor_01/Active`.
3. Enable Value and Quality; leave Timestamp unchecked.
4. Copy the body from `pause_on_detection.py` into the generated `onTagChange`
   function, keeping its header and indenting every body line once. This is not
   a Project Library module or a Pause-button event. Save the project.

The handler checks fresh good-quality True and a good-quality False latch, sets
the latch before calling `bambuP1s.command('Pause')`, and does not call Resume.
Install one trigger in one project; duplicate events create duplicate command
paths. The existing Pause button remains unchanged.

## Test, latch behavior and troubleshooting

After saving, initial subscription is deliberately ignored. Wait for a fresh
good-quality False, then enter the zone to create a new True. Check the sequence:

1. Active turns True: SAM observations reached Ignition.
2. PauseRequested turns True: the event set its request latch.
3. Printer pauses: the connector and printer completed the action.

The latch means **already requested**, not continuous transmission or confirmed
pause. It stays True after the zone clears, when printing is resumed manually,
and even if a downstream command fails. For another supervised test, first
confirm Active is False with good quality, manually clear PauseRequested, then
resume manually. Clearing the latch sends neither Pause nor Resume by itself.
The handler does not watch the latch and waits for a subsequent Active event.

If Active changes but the latch stays False, check the event is saved/enabled,
the watched path exists, Active quality is good and the latch path is writable.
During setup a duplicate Active tag was removed; the event still watched its old
path, so nothing ran. Updating the path to the final conveyor_01 location fixed it.
If the latch sets but the printer does not pause, check Gateway logs under
PersonDetectionPause and `[default]BambuP1S/Commands/Result`. The existing library
queues a request for its poller; successful function return/logging is not a
printer acknowledgement, and later failures may appear only in command result.

## Next work — planned, not implemented

- Add an explicit SCADA Reset / Re-arm button that checks fresh clear detection
  before clearing the latch. Keep reset independent of Resume and machine Start.
- Measure capture, inference, rule confirmation, bridge, OPC and command delays
  separately before tuning the roughly three-second observed response.
- Test stale data, quality recovery, occlusion, disconnects, failed commands,
  restarts, rapid transitions and reset during active detection.
- Review architecture and consolidate the validated experiments into the MVP,
  then test adapting the generic contract to another SCADA application.

The saved examples document this milestone; they do not modify the Gateway,
deploy a new Perspective screen, add Reset or alter a running printer.
