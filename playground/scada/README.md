# Single-printer Perspective project

## Live detection-to-Pause checkpoint - October 31, 2026

The owner confirmed camera -> SAM 3.1 -> vLock Bridge -> OPC UA -> Ignition
Gateway event -> printer Pause. The final Active/latch paths, Gateway script,
minimal tag import and troubleshooting are in the
[SCADA integration guide](../../integrations/ignition/SAM_BRIDGE.md). The estimated
three-second response is an owner observation, not an instrumented measurement.
Reset/re-arm UI and latency improvements remain planned. The original screen ZIP
is unchanged; the additional tags/event are configured separately.

## Development milestone - October 30, 2026

This playground experiment prepares a small physical test machine before industrial
integration. We built an Ignition Perspective SCADA screen and a local MQTT bridge
connecting SCADA to a Bambu Lab P1S. This is an intermediate development milestone,
not the finished industrial application.

```text
P1S <-> MQTT/TLS bridge <-> local HTTP <-> Gateway poller <-> Tags <-> Perspective
```

Owner-tested: the redesigned screen imports and renders in Ignition, live nozzle
and bed temperatures and connection status are displayed, and an actual print was
stopped from SCADA. Pause and Resume are implemented and checked offline; their
separate live confirmation is still pending. No AI is required for this slice.

### Next steps - planned

1. Develop the standalone vLock application and its state/command contract.
2. Connect SAM 3.1 observations to vLock, preserving worker locks independently of AI inhibits.
3. Connect vLock to SCADA and test the whole vision-to-machine workflow.
4. Fine-tune and test edge cases, stale data, disconnects, fallbacks, command
   failures, restart recovery, and explicit release/reset behavior.
5. Package a reusable application so SCADA developers can integrate vision into
   their workflows through documented equipment mappings and endpoints.

These steps are not implemented by this experiment. Clearing an AI inhibit must
not release a worker lock or automatically resume equipment.

## Files and reproducibility

- `project/`: readable Perspective views, Gateway library, page configuration and timers.
- `bridge.py`: source for the Ignition HTTP-to-tag bridge.
- `connector/p1s_service.py`: MQTT-to-HTTP bridge snapshot, including dedicated Resume.
- `connector/.env.example` and `connector/requirements.txt`: fresh-machine configuration.
- `output/single-printer-perspective.zip`: native project resource import.
- `output/bambu-p1s-tags.json`: tag import for a fresh provider or inspection.
- `build_project.py`, `test_project.py`, `enable_resume.py`: build, tests and optional legacy upgrade.

Only generic configuration defaults are included. Credentials, actual printer
serials, local logs, certificate pins and service wrappers are not published.

## Run the bridge on a new test PC

Use Python 3.12. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r playground/scada/connector/requirements.txt
Copy-Item playground/scada/connector/.env.example playground/scada/connector/.env
```

Edit that local `.env` with the actual IP, printer serial and LAN access code. Then:

```powershell
.\.venv\Scripts\python.exe playground/scada/connector/p1s_service.py --check-config
.\.venv\Scripts\python.exe playground/scada/connector/p1s_service.py
```

Keep the terminal running. If the existing BambuP1SConnector Windows service is
running, use it instead of starting a second instance. Its wrapper/installer is
not included; the source can run in the foreground. No existing private settings
need to be replaced. Check status from another PowerShell terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8876/status |
    Select-Object mqtt_connected, online, state, nozzle_temp, bed_temp, age_seconds
```

The connector uses certificate pinning on first local use (trust on first use),
then rejects changed certificates. Pins stay under ignored `state/`. Confirm the
printer IP on a trusted local network before first connection. Unlike the separate
one-reading experiment, this snapshot does not validate a CA chain and serial
hostname. Its HTTP API binds to loopback for the Gateway on the same PC; it is
not a public remote-control endpoint.

Earlier optional camera and job-start code remains in the snapshot. This screen
never calls it. The example disables the camera and leaves job launch unset.
The connector currently requests full status about every five seconds; request
rate and printer-load tuning remain experiment limitations.


Native Ignition Perspective project for one Bambu Lab P1S. Plain white screen,
one printer schematic, nozzle and bed temperatures, machine state, connector and
MQTT status, report freshness, and Pause / Resume / Stop-cancel buttons.
No camera panel, print-job launch, farm simulation, or additional printer data.

## Install on the existing Gateway PC

1. Back up the current Ignition project. Keep the running connector configuration
   and its private environment file unchanged.
2. Only for an earlier installed service without Resume (the bundled source already
   supports it), open PowerShell **as administrator** from the repository root and run:

   ```powershell
   .\.venv\Scripts\python.exe playground/scada/enable_resume.py
   Restart-Service -Name BambuP1SConnector
   ```

   The patch backs up the service source alongside the original, then adds only
   a Resume action. It refuses unexpected source structure. Restarting the
   connector briefly interrupts telemetry; the patch sends no printer commands.
   If the service is busy handling a command, wait for that command to finish.
3. Import `output/single-printer-perspective.zip` as an **Ignition project resource
   export**, using Designer File > Import, into the existing project. Select the
   Dashboard view, page configuration, `bambuP1s` project library, and timer resources.
   Replace the matching resources. This file is not a Gateway backup.
4. Disable the manually created `PrinterStatus` timer from the earlier console
   setup. Keep exactly one printer poller: `bambuP1sPoll`, enabled, 2000 ms,
   Fixed Delay, Dedicated. The old `printerFarmTick` resource stays disabled.
   Also disable duplicate pollers in other Gateway projects, if any.
5. Save the project. The poller creates only missing tags under
   `[default]BambuP1S`; existing configuration and tag values are preserved.
   `output/bambu-p1s-tags.json` is supplied for inspection or a fresh installation;
   it is not necessary to overwrite existing tags. The provider must be named
   `default`; change the ROOT constant and view bindings together for another provider.
6. Launch the project's Perspective session and open `/printer-farm` or `/`.
   Confirm both temperatures, MQTT status, printer state, and report age update.

The project library's automatic missing-tag creation is the same mechanism used
by the supplied original export. It does not require an OPC device configuration.
All connector HTTP calls run on the Gateway; remote browsers do not call localhost.

## Controls

- **Pause** requests pausing a Running print.
- **Resume** requests resuming a Paused print. It never uses the old Start action
  and cannot launch a new print file. Enable the supervisory system first.
- **Stop / cancel** cancels a running or paused print. It remains available while
  another command is pending and while supervisory enable is off. It is not an
  emergency-stop or electrical isolation function.
- The result line distinguishes a request, printer acceptance, and confirmed
  state. Always use the machine-state display to observe the actual state.
  Commands are not automatically retried after an unknown outcome.

`Commands/Pause`, `Commands/Resume`, and `Commands/Stop` are momentary Boolean
request tags. Set one True to request an action. The poller consumes it and resets
it False; Stop takes precedence over simultaneous requests. View buttons use the
same tags. `Commands/Busy` and `Commands/Result` provide feedback. A True request
is not evidence of a successful printer action.

Top **System Start / Stop / Reset** are separate supervisory controls. Start
enables Resume; Stop and Reset disable it. They do not send printer commands,
clear printer faults, release worker locks, or claim that a machine is stopped.
They are explicitly labelled `vLock pending`. No vLock integration is implemented
in this package. Monitoring continues when supervisory enable is off.

After project-script reload or Gateway restart, supervisory enable starts off
and any old command requests are discarded. Review the physical machine before
enabling the system. Actual worker-lock and AI-inhibit rules remain future work.

## Data quality

The connector determines MQTT report freshness (currently 30 seconds). The view
also hides data and disables printer commands if the Gateway poll is more than
10 seconds old. Invalid temperatures display `--`; the last numeric tag value is
retained with its validity flag False rather than overwritten with zero.
These temperatures are last reported readings, not a measurement accuracy claim.

## Build and verification

From the project folder:

```powershell
.\.venv\Scripts\python.exe playground/scada/build_project.py
.\.venv\Scripts\python.exe playground/scada/test_project.py
```

Seven offline checks cover: temperature and disconnect handling; missing/NaN
values; separate system controls; single consumption and Stop precedence;
dedicated Resume dispatch and supervisory gating; ZIP resources/bindings;
and the connector patch rejecting Resume for Idle/Running/Completed while
publishing only `resume` for Paused. Tests use mocks and send no real commands.
Tests use the bundled connector source; no installed service or private settings are required.

The owner verified MQTT telemetry, Designer HTTP access, the redesigned Perspective
screen, and stopping a real print from SCADA. The Resume patch was applied and the
installed service restarted. Separate live Pause/Resume evidence, restart recovery,
other firmware write permissions and industrial machine behavior remain unverified.
This is not an end-to-end vision/vLock test.

During a disposable test print: confirm Running, click Pause and observe Paused,
click System Start then Resume and observe Running. Finally test Stop/cancel and
observe the actual printer result. Test cancellation only on a job you intend to
cancel. If the connector reports authorization failure, check its firmware/mode;
successful telemetry alone does not verify write permission.

## Sources

- https://docs.inductiveautomation.com/docs/8.1/platform/scripting/scripting-in-ignition/gateway-event-scripts
- https://www.docs.inductiveautomation.com/docs/8.1/appendix/scripting-functions/system-net/system-net-httpClient
- https://www.docs.inductiveautomation.com/docs/8.1/appendix/components/perspective-components/perspective-input-palette/perspective-button

The supplied original project export and tag file are unchanged. No running
Gateway project or connector service is changed by building this package.
