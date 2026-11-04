"""Reference Gateway Tag Change handler for the owner-tested printer experiment.

Paste the function body into Ignition's generated onTagChange function.
Watch only [default]vLockBridge/vLock/conveyor_01/Active (Value + Quality).
Requires the existing bambuP1s project library and Boolean Memory PauseRequested.
This file does not install or enable a Gateway event by itself.
"""


def onTagChange(initialChange, newValue, previousValue, event, executionCount):
    logger = system.util.getLogger("PersonDetectionPause")
    latchPath = "[default]vLockBridge/PauseRequested"

    if not initialChange and newValue.quality.isGood() and newValue.value == True:
        active, requested = system.tag.readBlocking([
            str(event.getTagPath()),
            latchPath
        ])

        if (active.quality.isGood() and active.value == True
                and requested.quality.isGood()
                and requested.value == False):
            # Set before requesting; further detections cannot request again.
            written = system.tag.writeBlocking([latchPath], [True])[0]

            if written.isGood():
                try:
                    bambuP1s.command("Pause")
                    logger.info("Pause requested from person detection.")
                except Exception as exc:
                    logger.error("Pause request failed: " + str(exc))
