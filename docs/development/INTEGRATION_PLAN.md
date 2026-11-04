# SCADA integration plan

**Design draft. No endpoints, adapters, or schemas are implemented yet.**

## Developer experience

A SCADA developer should be able to install the app, configure a connection, register equipment, map signals, verify the handshake in a simulator, and activate approved monitoring without reading inference internals.

The final documentation must include a quickstart, complete endpoint reference, request/response examples, authentication, equipment mapping, network configuration, error codes, troubleshooting, and a working Ignition example.

## Contract checklist

- Equipment IDs and connection identity.
- Inputs: running/stopped/fault state, timestamps, data quality, heartbeat, and command acknowledgement.
- Outputs: supervisory inhibit state, stop request, active reasons, reset requirement, event identity, and health.
- Explicit separation between request accepted, command delivered, and equipment confirmed stopped.
- Documented ownership: which component controls each state and evaluates permissions.
- Versioned schemas; units and timestamps; correlation IDs; idempotency and ordering.
- Timeouts, stale inputs, lost communication, retries, duplicate handling, and restart reconciliation.
- Worker-lock apply/release rules, AI inhibit clearing, acknowledgement, reset, and explicit restart.
- Restricted command destinations and authenticated write access.

Tag names are developer-defined mappings. A connection or adapter must translate the app contract into the SCADA system's actual signals. Mapping a name alone does not establish connectivity.

## First reference

Use an isolated Ignition gateway or simulator. Document both directions: SCADA machine-state input to the application and application event/request output to SCADA. Prove stop acknowledgement separately from sending a request. Retain visible communication health.

## Machine reuse

A conveyor and a glass cutter share equipment, source, zone, rule, and signal-binding concepts. Machine-specific geometry and behavior must be explicitly configured and tested. Do not claim arbitrary machine support before validating it.
