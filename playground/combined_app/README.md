# Combined application UI playground

## Selection feedback and event bounds

Configure now shows an explicit area-selection indicator with vertex count.
Its card title changes after selection. New zones start with an example outline
that must be drawn/adjusted or explicitly confirmed with Use this area. Drawing
has a separate in-progress state; Reset area returns to an unselected outline.
Saving a zone requires a selected area. Existing configured drafts retain their
selected area during migration.

Recent events shows the latest **five** entries. Earlier entries expand into a
scrollable history. Workspace settings controls the retained limit per zone:
5, 20, 50, 100 (default), or 500 (maximum). Reducing the limit removes oldest
simulated entries immediately; Save workspace persists the bounded draft.
This is browser-only history, not a backend event-retention implementation.

Browser QA confirmed five recent plus two earlier rows from seven events,
trimming to five, selection/reset/confirmation feedback, and no browser errors.

## Final UI polish

- Camera setup combines zone identity and camera fields in one compact card.
  Configure and Monitor use a small source summary instead of a connection card.
- Screen titles now change with the step: Camera setup, Configure zone, Monitor
  zone. The zone identity stays in the subtitle and breadcrumb. Renaming updates
  the breadcrumb immediately; it no longer looks like a stale page title.
- Monitor has an explicit Enable / Disable monitoring button. Remote enable is
  separate; re-enabling waits for a fresh observation. Advanced details expand
  inputs, output validity/reason, limitations and a JSON debug snapshot. The
  expansion remains open while sample results change.
- System monitor adds application-wide zone filtering, input/output summaries,
  performance placeholders and debug snapshots. FPS, GPU load, dropped frames
  and end-to-end latency are reported as unmeasured, not fabricated benchmarks.
- Configure includes contextual ? help, an IF/THEN preview, an expandable AND/OR
  condition builder (up to six conditions), and a Meta configuration helper UI.
  The first condition uses the primary target; additional concepts and relations
  are editable. Removing conditions and changing the Boolean combination are
  supported. There is no Boolean rule runtime or natural-language parser here.
- The Meta helper previews fixed templates for rule drafting, limitations and
  Unknown debugging. It makes no API calls, applies no settings automatically
  and uploads no images. Interactive object selection is explicitly planned;
  polygon drawing remains the actual browser interaction.

Persistence is already implemented in the existing monitoring experiment:
`playground/monitoring/zone_rules.py` requires at least two fresh observations
spanning the configured duration. It is app-side confirmation, not a SAM model
parameter. The current local SAM adapter uses four-frame windows; tracking IDs
are scoped to a window and do not prove continuous occupancy between samples.

SAM accepts concrete object phrases rather than Boolean instructions. A rule
such as person AND dog needs app-side combination of fresh observations, with
separate concept requests where required. The free-text description and structured
builder will need explicit translation/validation and a reviewed source of truth.
This prototype does not infer one from the other or execute either.

References: [Meta prompting guide](https://dev.meta.ai/docs/sam/segmenting),
[SAM 3.1 release notes](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md).

Recommended first wiring milestone: one camera, one reviewed zone condition,
one versioned observation output, freshness and enable gating, plus measured
latency. Keep the Meta assistant advisory. Add combined rules only after defining
timestamp alignment and three-valued AND/OR semantics; unknown evidence must
never be silently treated as a negative detection. Keep worker locks and machine
actions in their existing external ownership.

UI QA additionally checked Monitor button gating, debug expansion retention,
person AND dog preview, help dialogs, helper limitations, System monitor zone
filtering and absence of browser errors. None of these are live inference tests.

## Current layout — Zones dashboard

The current iteration replaces the original workspace wizard with:

- A **Zones dashboard** with camera scorecards, enable switches, an output,
  a recent event and Add zone controls.
- Three steps per zone: **Camera → Configure → Monitor**. Camera connection
  and preview stay on the left on desktop; configuration or results sit on the right.
  The camera fields collapse to a connection summary after the first step.
- A new zone must have a name and camera address before its simulated connection
  can be made. Configure is gated by camera connection; Monitor is gated by saving
  the zone's target, instruction, output and validity settings.
- **Shared Integrations** in the sidebar. OPC UA server/client, MQTT broker
  connection/proposed hosting, HTTP, addresses and ports are configured once.
  A table previews output and control paths for every zone.
- **Workspace settings** to name the collection, select intended application
  placement, and export the draft. Save workspace persists zones and shared settings
  under a new browser-storage key. The old iteration's draft remains untouched.
- **Unknown handling inside each zone**: a minimum model score, uncertainty policy
  and an optional planned second-check profile. A model score is not a calibrated
  probability. The instruction text and second-check choices are not executed.
- **Monitoring** with local enable, a simulated SCADA enable input, model score,
  result age, illustrative inference time, output values/validity/reason, and the
  two newest events. Disabled monitoring produces null/unavailable, never Clear.
  Re-enabling starts in Unknown until another simulated result is selected.

All behavior remains UI-only. Preview connections do not contact a camera; model
results and timing numbers are explicit samples. No OPC UA service, MQTT broker,
HTTP application API, model request or real SCADA write has been added.

Assumptions for this revision:

1. A dashboard “zone” is one named monitoring task with one camera and polygon.
2. All zones share workspace-level integration endpoints and security profiles.
3. Local enable and SCADA enable must both be true when remote control is allowed.
   Neither input starts equipment or releases worker locks or SCADA latches.
4. Confidence and validity are separate outputs. Missing/expired data stays Unknown
   regardless of the optional second-check selection.
5. MQTT hosting and remote deployment remain product proposals, not capabilities
   of the existing experiment adapters.

Later decisions: whether one camera should serve many dashboard zones; whether a
zone needs several output rules; how SCADA enable requests are authenticated and
persisted; and which model-score calibration and second-check policy are acceptable.

Browser QA verified new-zone navigation gates, a dog_detected example, polygon
keyboard editing, local/SCADA enable gates, re-enable freshness, the five result
presets, shared OPC UA mode switching and saved workspace restoration. Desktop
camera-left placement was inspected. No live integration tests apply to this UI.

## Previous iteration reference

The original design notes below are retained as history. Its seven-screen wizard
and review gate describe the earlier layout, not the current Zones workflow.

One browser-only UI prototype for **vLock-AI Vision**. It combines the camera / SAM
configuration workflow and the vLock Bridge configuration workflow for review
before service integration. It does not import or change either experiment.

## Open

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m http.server 5070 --bind 127.0.0.1 --directory playground/combined_app
```

Open <http://localhost:5070>. This is a static file preview, not an application
backend. Stop it with Ctrl+C. No package installation, model worker, camera,
broker or SCADA Gateway is required. You can also open `index.html` directly;
browser draft storage on file URLs varies by browser. Use the HTTP preview for
consistent local draft storage.

## Included UI

- **Overview:** one workspace, illustrated scene, configuration summary and
  recent simulated events.
- **Camera source:** camera name/type/address, credential reference and local
  or cloud vision-runtime settings. No secret entry fields.
- **Zone & rule:** target phrase, polygon drawing, pointer/keyboard vertex
  editing, overlap/inside/absence condition, persistence, validity and output type.
- **Equipment:** vendor-independent asset identity, location and signal mapping.
- **Connections:** intended placement alongside a Gateway on its host, or on a
  separate network host; OPC UA server/client, MQTT and HTTP configuration views.
  OPC UA client mode shows read and write mappings; server mode shows published
  signal identities. All protocol choices are UI configuration previews.
- **Test workspace:** explicit simulated Active, Clear, inference unavailable,
  expired observation and connection-loss presets. Illustrative output JSON,
  independent known/quality fields, and session-only event history.
- **Review:** configuration summary, basic field checks, five-scenario preview
  checklist and a UI-layout acknowledgement. Editing settings invalidates that
  review and requires previewing the scenarios for the revised draft again.
- **Save / export:** Save stores configuration in this browser only. Export
  downloads `vlock-workspace-draft.json`, marked `prototype: true` and
  `services_connected: false`. It is not a deployment or runtime configuration.
  Event history and review acknowledgement reset on reload; a saved draft's
  configuration remains. Reset affects this prototype's browser storage only.

## Deliberate boundaries

The code consists of static HTML, CSS and JavaScript for UI interactions. There
are no camera requests, inference calls, protocol clients/servers, application
API routes, authentication, installer, Gateway module or machine commands.
The page's Content Security Policy blocks script-initiated network connections.
The only server needed for preview is Python's standard static file server.

The scene is an original SVG illustration. The person, boxes and monitoring
states are synthetic. No actual camera footage, credentials, saved experiment
configuration or equipment state is read. Addresses and node paths are examples.

SCADA can be any platform with a future supported adapter. No printer-farm UI,
printer adapter or Ignition screen is embedded here. Worker locks, SCADA latches,
machine actions and acknowledgement remain externally owned in this prototype.
Clearing a simulated observation changes neither worker locks nor SCADA state.

The deployment screens illustrate desired flexibility. Running alongside a
Gateway on its host is not the same as installing a native Gateway module.
Remote camera support, remote networking and encrypted server-mode deployment
still need actual service implementation and validation after UI approval.

## Assumptions for this iteration

1. Start with one camera, one zone/rule, one equipment asset and one selected
   integration per workspace. A multi-camera or multi-asset UI is a later decision.
2. vLock remains a standalone application with a configurable SCADA connection.
   Initial Gateway-host deployment means a process alongside the Gateway, rather
   than an implemented vendor-specific plugin.
3. Existing model/camera/bridge experiments stay intact. Promotion into `web/`
   and production service directories waits for owner review.
4. Runtime secrets will eventually live on the server; this UI accepts only
   profile/reference names. Browser storage and exported drafts are not secret stores.
5. SAM local/cloud, source types and MQTT/HTTP screens describe future product
   choices; displaying them does not establish support in the existing adapters.
6. Clear, Active and unavailable observations remain separate. The application's
   connection health is separate from observation freshness.
7. Service integration comes after layout and workflow approval. UI review does
   not arm a rule, start monitoring or approve live control behavior.

## Questions for later review

- Is this navigation order right, or should camera, zone and rule share one screen?
- Should one camera support several zones/rules, and should a workspace contain
  several assets? Which relationship should the next UI revision make easiest?
- Does “install in the Gateway” mean a native Ignition module, an embedded/linkable
  page, or a standalone application installed on the same host?
- Should connections be shared across multiple assets, or configured per asset?
- Should OPC UA server and client modes run simultaneously for different mappings?
- Should the primary preview output be a condition, count/measurement, event,
  or a selectable combination? The current prototype offers one output choice.
- What should the first production UI expose for worker locks and SCADA-owned
  latches: status only, links to SCADA, or a separately specified workflow?
- Should guided natural-language setup join this first workflow, or follow after
  manual configuration and real service integration are stable?

## Verification

Syntax check:

```powershell
node --check playground/combined_app/app.js
```

Browser QA covered navigation, editing and saved draft restoration, keyboard
polygon editing, protocol and OPC UA mode switching, all five simulated state
outputs, review gating and edit invalidation. Desktop and narrow-screen layouts
were visually inspected; the narrow viewport had no document-wide horizontal
overflow. These are UI checks, not model, transport, latency or machine tests.

## Design inputs

- `web/monitoring.html` and `playground/monitoring/README.md`: camera, target,
  polygon, overlap/persistence, freshness and observation workflow.
- `playground/segmentation/README.md`: local/cloud runtime and windowed tracking.
- `playground/vlock_bridge/`: identities, condition/measurement outputs,
  known/unknown semantics, heartbeat and protocol choices.
- `docs/PRODUCT_DIRECTION.md` and `docs/PLAN.md`, also reviewed on the public
  repository: standalone application, flexible integration, and review before activation.

This is the prototype to tweak. It has not been promoted to the main application.
