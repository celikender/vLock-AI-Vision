# Printer-farm Gateway site setup

vLock publishes observations. This demo's customer-side Ignition Gateway decides
machine actions. No product code or settings under web/, services/ or ignition/
are changed. SCADA Start/Stop/Reset never control vLock monitoring.

## Build and import

From the repository root:

```powershell
.\.venv\Scripts\python.exe demo_site/printer_ignition/build_bundle.py
.\.venv\Scripts\python.exe -m unittest discover -s demo_site/printer_ignition -p "test_*.py"
```

1. Back up the running printer project. Import the inner
   `output/printer-farm-perspective.zip` from the clean deployment bundle.
2. Replace **both libraries** (`bambuP1s`, `printerSite`), **both enabled timers**
   (`bambuP1sPoll`, `printerSiteTick`), `PrinterFarm/Dashboard` and the disabled
   **Tag Change > PauseOnDetection** resource. Keep `printerFarmTick` disabled.
   This is a project-resource import, not a Gateway backup.
3. Verify `PauseOnDetection` is **disabled** in Gateway Events before enabling the
   new timer. Its packaged handler is a no-op and its enabled flag is false.
   The installed demo previously had this event enabled; the export only changes
   that running configuration after import/save. Disable any duplicate event in
   another printer project too. There must be one automatic pause controller.
4. `printerSiteTick`: **250 ms, Fixed Delay, Dedicated**. It reads cached qualified
   source tags, evaluates the latch and queues Pause. It does not perform HTTP.
   `bambuP1sPoll`: **1000 ms, Fixed Delay, Dedicated**. It handles printer telemetry
   and consumes command requests; HTTP command workers run asynchronously.
5. Missing tags under `[default]BambuP1S` are created automatically. Preserve the
   existing tags/configuration; do not overwrite them with the full optional JSON.
   Keep the working connector and MQTT/OPC connections. No reinstall is needed.
6. Confirm `Config/VisionZonePath` is **[default]vLock/A-101**. The existing imported
   tags are used directly: State, Quality, Reason, plus Bridge/Online and
   Bridge/HeartbeatCounter under `[default]vLock`. Every original qualified value
   is checked; the Vision/ mirror is for display only.

P1S-01 is the only connected station. The other two cards remain Offline with no
commands or camera requests. The original files/exports remain available locally.

## Site behavior

| Condition / control | Gateway behavior |
|---|---|
| Good-quality State Active | Latch immediately on the next site scan. |
| State Unknown, any of the five source tags not Good, Quality not Good, Online false, or unsupported state such as Valid | Latch after 2 continuous seconds from first observation. Recovery restarts the debounce. |
| HeartbeatCounter unchanged | Latch only after more than 5 seconds, even if a frozen State still says Clear. |
| New latch | Disable Resume, invalidate queued Resume intent, and call `bambuP1s.command('Pause')` once when Running is observed. Never call Stop. |
| System Stop | Set the latch and request Pause for Running; an explicit further Stop click may request another Pause. |
| Either Reset button | Clear only with State Clear, all source qualities Good, Quality Good, Online true and an observed moving heartbeat. Leave enable off. No connector command. |
| System Start | Require a valid Reset, no latch and current Clear/healthy vision; enable operator Resume only. No print start. |
| Resume | Explicit operator click, Paused printer, current reset/start permissives and a fresh source recheck immediately before dispatch. |
| Clearing vision / restored communications | Never clears the latch or resumes a job. |
| Cancel job | Explicit operator action only. Calls Stop and cancels the job; site logic never uses it. |

A transient loss of Clear also invalidates any queued operator Resume, even if
it recovers before the two-second latch debounce. Recovery never releases an old
Resume intent; the operator must click again.

A single counter read is not proof of movement. After reconnect/offline or Bad
counter quality, observe a subsequent change before Reset can succeed. Source
Reason is shown/logged for people; its wording does not drive decisions.

A new latch retains one pending Pause intent if the printer's Running report has
not arrived yet. It consumes this once at the first observed Running state; it
never retries an attempted command automatically. If a Resume HTTP worker is
already pending, Pause has its own gate and waits on the Gateway command lock;
that wait does not block the site watchdog. Inspect actual printer state and
command feedback after any unknown outcome. This is not a measured stop-time claim.

On project-library reload, enable and ResetValid become false, old command tags
are discarded, and a new heartbeat observation is required. The stop latch itself
is preserved; the generated latch tag uses Database value persistence. Confirm
that property if an older existing tag was manually created. A fresh installation
starts unlatched but still requires a valid Reset and Start before Resume.

The manual-control deployment switch `Config/ControlRequestsEnabled` does not
turn off the automatic site watchdog. Disable the site timer explicitly for a
controlled maintenance/test session when appropriate.

## SCADA tags

`System/StopLatched`, `StopReason`, `Enabled`, `ResetValid`, `CanReset`,
`ResumeAllowed`, `HeartbeatMoving` and `Message` belong entirely to the demo
Gateway. No worker-lock or physical isolation tag is written or released.
`Controls/Request` remains a local audit snapshot with action/target/session/sequence;
it is not a vLock input or an additional command consumer. The event feed holds
25 entries; command acceptance is separate from actual physical state.

## Optional camera

Each card contains an enlarged fixed camera frame. P1S-01 refreshes the connector
`/camera.jpg` every second while that view's camera is On; the Offline cards display
placeholders without any requests. The Gateway passes the original JPEG as base64;
no transcoding or frame queue. Failure replaces the previous image with an
Unavailable placeholder without resizing the card. Browsers receive neither the
connector URL nor the printer access code. Use one demo session to limit traffic.

The Camera On/Off button is local to each open view. Off clears the image and
stops snapshot requests, including discarding a response returning after Off.
It does not turn off the connector's background connection to the physical camera.
The P1S's own frame rate still limits how often a new image is available.


Set `CAMERA_ENABLED=true` in the existing connector's private environment file
and restart that connector when ready. The example defaults to false. Do not start
a second connector on port 8876. The P1S uses TLS/JPEG on port 6000, not X1 RTSP.
This session did not change private settings, restart services or verify live camera access.

## Verification before recording

1. Confirm source State/Quality/Reason and a moving counter at the actual A-101
   paths. Check the new site timer and disabled old event in the correct project.
2. With a disposable Running job, trigger Active. Confirm one Pause request and
   actual Paused state. Keep Active and confirm no repeated automatic requests.
3. Clear the zone. Confirm latch remains set and print remains Paused. Reset:
   latch clears, enable stays off. Start: enable on, still Paused. Click Resume:
   only then confirm Running.
4. Check a refused Reset during Active, Unknown, Bad quality, Offline and a frozen
   counter. Test Unknown shorter than 2 seconds and over 2 seconds separately.
5. Check System Stop pauses rather than cancels. Verify the camera On/Off control.

Automated tests use a controlled clock and a stand-in Ignition system; physical
pause timing and the new full chain still need a live Gateway/owner test. An
Ignition offline parser/Jython check does not deploy any resources. This package
is a demo supervisory control, not emergency stop or physical isolation.
