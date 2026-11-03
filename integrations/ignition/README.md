# Ignition reference integration

Reference integration for the standalone vLock application. The application is not hosted inside Perspective.

Start new SCADA work from the [fixed zone tags](ZONE_TAGS.md): every zone publishes
the same tag names under a fixed tag key, with an Ignition UDT download.

The bridge also offers an experimental [Ignition OPC UA client mode](OPC_UA_CLIENT.md)
for mapped machine-status reads and observation writes to Memory tags. Isolated
read/write and encrypted login tests pass; live Ignition client-mode validation
is pending certificate trust, credentials and explicit test-tag mappings.

The owner confirmed live SAM person detection through vLock Bridge and OPC UA into Ignition, triggering one printer Pause request. See [the setup, Gateway script, tags and reset limitations](SAM_BRIDGE.md). This remains an experimental integration, not the consolidated MVP.

## Single-printer experiment

The [plain P1S Perspective project](p1s_printer/README.md) provides a native
SCADA display, a Gateway HTTP-to-tag bridge, and separate printer/supervisory
controls. It uses the existing local MQTT connector. The original standalone
application remains separate. The owner verified live telemetry, the imported screen and Stop/cancel of a real
print. Manual Pause and the end-to-end detection-to-Pause path were subsequently owner-tested on October 31, 2026. The new setup is documented above; a SCADA reset/re-arm button is still planned.
