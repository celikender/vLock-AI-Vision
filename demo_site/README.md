# Demo site

**This folder is not part of the vLock-AI Vision product.** It is the customer side of the demo: a
camera and a machine under a SCADA system, standing in for a real plant. The app only meets it through a
camera address and its published status tags, and any other SCADA or camera can take its place. These
projects are kept here for the hackathon and move to their own repositories afterwards.

| Folder | What it is | How it meets vLock-AI Vision |
|---|---|---|
| [pi_camera](pi_camera/README.md) | Raspberry Pi 5 USB camera service and boot installer | The app reads frames from its HTTP address |
| [printer_ignition](printer_ignition/DEMO_SETUP.md) | Bambu P1S printer dashboard in Ignition Perspective, a local MQTT connector, because the printer has no OPC UA, and example customer-side stop and reset logic | Its Gateway scripts read the fixed zone tags. The app sends it no commands |
| [detection_pause](detection_pause/SAM_BRIDGE.md) | The earlier detection-to-Pause experiment and its Gateway script | Replaced. It watches an older tag path and does not react to the fixed zone tags or to Unknown |

The product's own SCADA material is in [`ignition/`](../ignition/INTEGRATION.md).

## Perspective view

The view is `PrinterFarm/Dashboard`, titled "Printer farm | Operations". It has three printer cards.
`P1S-01` is the connected printer, and `P1S-02` and `P1S-03` show OFFLINE.

- **Status display:** machine state, a `Vision:` line with the zone state, program, nozzle and bed
  temperature, progress, time left, connector and MQTT status, and a Recent events table.
- **Stop latch:** the `printerSite` Gateway script latches at once on `Active`, after 2 s of `Unknown` or
  Bad quality, and after the heartbeat stays unchanged for more than 5 s. It then requests Pause once if
  the printer is Running. The message line shows `Stop latched:` and the reason. This is a stop latch on
  the SCADA side, not a worker lock.
- **Reset:** System Reset clears the latch only with `State` `Clear`, Good quality, the bridge Online and
  a moving heartbeat. System Start then enables Resume, and Resume is a separate operator click. A zone
  going back to `Clear` never clears the latch or resumes the print.

Setup steps are in the [demo setup guide](printer_ignition/DEMO_SETUP.md).

## Moved paths

These folders used to be `devices/pi_camera`, `integrations/ignition/p1s_printer` and
`integrations/ignition`.

**A Pi that was installed from the old path keeps running until you pull this repository on it.** After a
pull, its service points at a file that has moved, so run the installer again from the new path:

```bash
bash demo_site/pi_camera/install.sh
```

## Tests

From the repository root:

```bash
python -m unittest discover -s demo_site/pi_camera -p "test_*.py"
```

```bash
python demo_site/printer_ignition/test_project.py
```
