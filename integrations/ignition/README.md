# Ignition reference integration

Planned example connecting an isolated Ignition system to the standalone app through documented endpoints or an adapter. This folder will contain verified mappings, sample scripts, and troubleshooting when implemented. The application is not hosted inside Perspective.

## Single-printer experiment

The [plain P1S Perspective project](../../playground/scada/README.md) provides a native
SCADA display, a Gateway HTTP-to-tag bridge, and separate printer/supervisory
controls. It uses the existing local MQTT connector. The original standalone
application remains separate. The owner verified live telemetry, the imported screen and Stop/cancel of a real
print. Pause/Resume are implemented and checked offline; live confirmation is
pending. End-to-end vLock integration is planned.
