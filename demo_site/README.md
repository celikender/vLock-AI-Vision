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
