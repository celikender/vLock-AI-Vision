# Development log

## 2026-10-31 - Owner-confirmed live detection-to-printer Pause

- Owner confirmed manual printer Pause works and then verified entering the camera
  zone causes a real printer Pause through SAM 3.1, monitoring rule confirmation,
  vLock Bridge HTTP input, OPC UA, an Ignition tag and a Gateway Tag Change script.
- Recorded the exact final watched tag path under conveyor_01 and the separate
  Boolean Memory PauseRequested latch. A deleted duplicate tag initially left a
  wrong watched path; correcting it enabled the live trigger.
- Added the owner-tested handler as readable reference source, a minimal additive
  tag-import example, and setup/troubleshooting instructions in integrations/ignition.
  The import JSON is new and not live-import tested; the owner configured live
  tags/event manually. Existing Perspective ZIP and printer controls are unchanged.
- Latch stays set after detection clears and blocks more Pause requests. A request
  is not proof of acknowledgement. No automatic Resume or reset UI was added.
- Owner estimates about three seconds from entry to pause. This is not a measured
  latency benchmark. Next: instrument delays, add a guarded SCADA reset/re-arm
  button, test edge cases, review architecture and consolidate into the MVP before
  adapting to another SCADA application.
- Publication checks passed: 119 Python tests (monitoring 24, segmentation 43,
  web 16, bridge 29, SCADA 7), JavaScript syntax and heartbeat watchdog checks.
  Offline Gateway-handler checks covered startup skip, bad quality, one request,
  latch retention and command failure; tag JSON parsed. No live machine commands
  were sent during these checks. The reference handler was checked with stubs,
  not an automated Ignition runtime.
- Included earlier pending monitoring/grounding performance changes and their
  existing report with the working publisher milestone; those hardware benchmarks
  were not repeated during this publication step. Unrelated Bambu temperature
  experiment remains local.


## 2026-10-30 - Experimental SAM monitoring to bridge publisher

- Reused the existing Monitoring Setup camera, local SAM and zone-event pipeline.
  Added an opt-in bridge section with an asset mapping, API acceptance/error
  status, and a link to the bridge. Existing configurations default to disabled.
- Added a SAM input section beside the bridge's existing manual workflow. Source
  sam publishes people_count and zone_condition through the existing HTTP API;
  MQTT and OPC UA use the existing shared state. Manual streams stay separate.
- Anchored validity to frame capture with a ten-second expiry. Missing, stopped
  or stale inference is Unknown, never a fabricated zero. Counts cover the whole
  image; the condition follows zone geometry and persistence. Publication uses
  bounded synchronous local requests without a retry queue or machine commands.
- 24 monitoring checks passed, including five new synthetic-result tests through
  an isolated bridge HTTP server, expiry, confirmation, Stop, disabled migration
  and transport failure. 16 web checks and 29 bridge checks passed; one initial
  bridge run had a Windows connection abort in origin rejection, then the full
  rerun passed. JavaScript syntax and heartbeat watchdog checks passed.
- Browser-checked both sections and saved target person with bridge publishing
  enabled for conveyor_01. Monitoring remains stopped for camera placement.
  Worker health responded ready, with model_loads=0; weights are not loaded yet.
- Started the local SAM worker and monitoring UI. Actual camera inference, new
  Ignition tag import and printer Pause remain for live owner validation. No
  existing printer control or automatic Resume logic was changed.


## 2026-10-30 - Timed heartbeat pulse and bounded history

- Clarified protocol connection monitoring versus an optional application heartbeat.
  The earlier diagnostic counter was calculated from uptime. Replaced that source
  with an explicit periodic task that toggles a Boolean pulse and increments its
  diagnostic count without requiring any API read. It does not monitor model health.
- Removed visible heartbeat counts from the page and adapter descriptions. The UI
  shows Online/Offline and last-heartbeat age. HTTP/MQTT expose heartbeat_pulse;
  OPC UA adds Bridge/HeartbeatPulse and HeartbeatIntervalSeconds. Default interval
  is one second; --heartbeat-seconds accepts 1-60 and advertises a matching timeout.
- Fixed the subscription instructions to include an absolute executable path.
  A read-only client started from the Windows home folder received alternating
  True/False from the actual local OPC UA pulse node.
- Changed the event view to the latest five rows. SQLite retains at most 1000
  history events by default; --history-limit accepts 5-100000. Superseded observation
  bodies are pruned, while each signal's current observation is preserved.
- Documented the bounded duplicate-protection window and replay cursor expiration.
  Existing event schema is migrated locally without renumbering revisions; the
  current 40 events were below the default limit and remained retained.
- Twenty-nine Python checks passed, including idle periodic pulses, retention,
  current-state preservation, legacy schema migration, replay metadata and real
  MQTT/OPC UA reads. JavaScript watchdog checks and syntax checks passed.
- Browser verification confirmed exactly five history rows and no visible count.
  Model connections, machine commands and the existing broker configuration were
  unchanged. The bridge remains running with the revised source.

## 2026-10-30 - Explicit Online/Offline and heartbeat signals

- Added bridge Online/Offline and adapter badges to the UI, with a visible
  elapsed-second heartbeat counter. Bridge availability remains separate from
  observation validity: Stale observations do not make a responsive bridge Offline.
- HTTP health/snapshots and MQTT availability now expose online, heartbeat_counter,
  session identity and a five-second watchdog timeout. OPC UA adds read-only
  Bridge/Online, Status, HeartbeatCounter and OfflineAfterSeconds nodes.
- The process counter uses monotonic elapsed time rather than observation time,
  UTC clock changes or event revisions. It adds no observation/history records.
  Adapter availability requires recent publication progress. The browser detects
  request failure or a frozen counter; duplicate responses cannot keep it Online.
- Documented receiver-side watchdog behavior. A stopped/frozen server cannot
  reliably publish Offline itself; MQTT Last Will and transport quality complement
  the consumer's timeout. A new process session permits the counter to reset.
- Twenty-four Python checks passed, including real MQTT/OPC UA heartbeat fields,
  independent observation expiry and adapter-progress timeout. JavaScript watchdog
  checks covered duplicate/frozen samples, loss, recovery and session reset.
- Browser verification observed all three Online badges, then Bridge Offline after
  stopping only this bridge. Restart restored Online automatically without reloading
  the page. The bridge is running again; the installed broker was unchanged.
- Closing browser connections are handled as lost readers rather than storage
  errors. Nineteen HTTP/core checks passed again after that response cleanup.

## 2026-10-30 - Optional MQTT and OPC UA outputs

- Added optional transport dependencies and a simple Integration form to the
  bridge playground. Broker/endpoint settings are saved beside the ignored
  database; status distinguishes saving settings from actual connection/publication.
- MQTT publishes retained QoS 1 JSON snapshots per bridge and asset, with online
  heartbeat and offline Last Will. Reconnect creates a fresh client and reads
  current state; it does not renew observations or replay old samples as fresh.
- OPC UA exposes read-only nodes with stable asset/source/signal IDs, numeric and
  JSON measurements, status, timestamps and complete asset snapshots. Expired
  observations have bad quality; unknown inhibit has a null DataValue and
  InhibitKnown=False. Client writes were rejected in the test endpoint.
- Both adapters share the HTTP store's expiration behavior and check freshness
  without a browser. Machine actions, latches, permissives and reset stay in SCADA.
- Found an existing running local Mosquitto broker on port 1883. Its service and
  configuration were left unchanged. A subscriber received the bridge's retained
  state and online availability; the asset state matched the HTTP API.
- Twenty-two checks passed, including actual isolated MQTT broker/subscriber
  delivery, retention, expiry, reconnect after an observation expires offline,
  graceful offline availability, and OPC UA client reads, read-only enforcement,
  numeric values, bad expiry quality and recovery to a fresh Clear. JavaScript
  syntax and dependency consistency checks passed.
- Browser verification enabled both adapters and observed MQTT Connected and
  OPC UA Running. Independent clients also read the live endpoints and matched
  HTTP state. No real model or machine command was used.
- These adapters are local-only experiments: plain MQTT JSON (not Sparkplug),
  read-only OPC UA NoSecurity, no MQTT observation/command subscription, and no
  LAN listener. Encrypted remote deployment and actual Ignition tag mapping
  remain unverified. All runtime changes stay under playground/vlock_bridge.

## 2026-10-30 - Clearer bridge signal type selection

- Addressed a reported condition-to-measurement conflict in the manual form.
  Switching output type now remembers a separate Signal ID for each type,
  starting with person_in_zone and people_count; custom IDs are preserved.
- Added an existing-signal hint and form validation before a conflicting type
  can be submitted. The API's fixed-kind contract and stored signals are unchanged.
- JavaScript syntax passed. Browser verification confirmed default/custom ID
  restoration, a conflicting ID being flagged, and successful publication of
  measurement value 12. Backend checks were not rerun for this UI-only change.

## 2026-10-30 - First standalone vLock integration bridge

- Agreed the integration boundary: vLock publishes observations, conditions and
  freshness; the consuming SCADA / PLC owns machine actions, permissives,
  interlocks, latching, worker-lock handling and reset. This refines the earlier
  standalone-control planning; no machine-control lifecycle is implemented here.
- Added an independent experiment under playground/vlock_bridge on port 5055,
  with manual condition buttons, measurement input, observation JSON, current
  output and SQLite event history. No main application or SCADA resources changed.
- Exposed local versioned API routes for observations, assets, event replay and
  health. Optional HTTPS accepts an existing PEM certificate/key pair. MQTT,
  OPC UA, model normalization and prompt-guided monitoring remain planned.
- Kept each asset/source/signal independent. Fresh active conditions aggregate
  to True; all-clear conditions to False; unavailable conditions to null when
  no fresh active condition exists. Measurements never generate an inhibit.
- Expiry and restart produce Stale/Unknown, preserving history without restoring
  old observations as current. Duplicate IDs do not renew validity or overwrite
  newer observations. Conflicting IDs and out-of-order timestamps are rejected.
- Seventeen checks passed, including temporary-database persistence, aggregation,
  concurrent duplicates, timestamp/expiry validation, HTTP boundaries and HTTPS
  with a temporary certificate verified by the client. JavaScript syntax passed.
- Browser verification observed Active, Clear, Unknown, automatic expiry, a
  numeric measurement, JSON submission and an idempotent retry. A process restart
  preserved history and required fresh observations. Inputs were simulated; no
  model or machine request was made. Owner validation and actual SCADA mapping remain open.
- This version accepts only local connections, with no remote authentication,
  stream removal or configurable mapping engine. The next integration step is
  validating one external client's reading of the contract before adding transports.

## 2026-10-30 - Plain single-printer Perspective export

- Reworked the supplied project export into one P1S screen: nozzle/bed
  temperature, machine state, connector/MQTT/report status, and Pause/Resume/Stop.
- Included a dedicated two-second Gateway poller, missing-tag initialization,
  momentary command tags, command feedback, and stale-value display handling.
- Separated System Start/Stop/Reset into clearly labelled supervisory enable
  state; vLock remains pending. These controls send no printer commands.
- Prepared an idempotent, backup-producing connector patch for dedicated Resume,
  which rejects non-paused states instead of using Start to launch a print.
- Seven offline checks passed, including mocked command routing and applying
  the patch against connector source. Tests now use the bundled snapshot.
- Owner imported/rendered the new screen, verified live temperatures and connection
  status, applied the Resume patch, restarted the connector and stopped an actual
  print from SCADA. Separate live Pause/Resume verification remains pending.
- Published the experiment under playground/scada with readable resources, tag
  import, native project ZIP, MQTT bridge source and generic local configuration.
  Original supplied exports remain unchanged; no credentials or runtime data are included.
- Next: standalone vLock, SAM 3.1-to-vLock observations, vLock-to-SCADA whole-system
  testing, edge cases/fallbacks, and reusable integration packaging. These are planned.

## 2026-10-29 - Monitoring Setup MVP in the existing PC application

- Added /monitoring to the existing localhost:5051 server, with camera setup,
  detection target, editable polygon, mask-based conditions, persistence and a
  local warning/event-log action. Existing camera/photo tools remain at /.
- Reused the existing Pi JPEG relay, SAM 3.1 GPU worker, dynamic text prompts and
  four-frame JSON adapter. The worker source and CUDA environment were unchanged.
- Saved camera/target/zone/rule configuration and the latest 100 events under
  ignored playground/data/monitoring. Credentials are backend-only and redacted
  from responses. Server restart restored setup/events and started stopped.
- Used real mask pixels rather than box intersection. Freshness, invalid masks,
  camera loss, resolution changes, prompt revisions and Stop preserve Unknown
  separately from Normal. No LLM or machine/SCADA command is used by this flow.
- Browser demonstration connected the real Pi, drew and dragged a zone vertex,
  saved the polygon and started person monitoring. Real masks overlapped the demo
  polygon by about 44%; fresh observations confirmed Warning. Cold results stayed
  Unknown. Changing the target to forklift preserved the zone and fresh empty
  results confirmed Normal. Both phases reported one model load.
- Restarted only the PC app and confirmed restored setup could generate another
  real warning using the still-loaded GPU model. Left monitoring stopped.
- 75 checks passed: 16 monitoring configuration/geometry/rule tests, 16 web route
  checks and the existing 43 segmentation tests. JavaScript syntax checks passed.
- Existing window latency can cause Unknown intervals between results at the
  10-second freshness limit. Persistence cannot establish continuous occupancy
  between sampled frames. Recognition accuracy and physical camera-unplug tests
  remain for owner evaluation. SAM-assisted zone selection and SCADA tag output
  are explicitly unavailable in this MVP.

## 2026-10-28 - Claude setup with local SAM raised-hand rule

- Corrected the monitoring architecture to Claude text-only setup followed by local SAM inference and deterministic geometry/event checks.
- Removed stand_up from the available monitor/API rules; its earlier experimental source remains preserved but is not called by monitoring.
- Added same-frame hand/head/person segmentation, normalized mask boxes, single-person geometry validation, above-head checks, head-relative movement, and two-observation activation.
- Missing/ambiguous masks and stale samples yield unknown; no camera image is sent to Claude from this loop.
- Live one-frame check returned one hand, one head, and one person with valid geometry. The new rule correctly remained unknown with only one detected hand. Inference took 44.52 seconds including initial load, then 0.86 seconds for head and 0.59 seconds for person on that same frame.
- Text-only Claude preparation returned the intended local SAM setup. Raised-hand gesture accuracy remains for owner testing; successful segmentation is not proof of physical identity or correct gesture classification.

## 2026-10-28 - Seated-to-standing playground rule

- Added stand-up prompt interpretation and explicit Claude vision mode with cloud-image disclosure beside Start.
- Confirmed seated observations arm the rule; confirmed standing observations emit person_stood_up. Starting standing does not trigger. Unknown/stale observations reset the baseline.
- Posture inference uses sampled single-person images, sequential requests, and a five-second pause. It does not use SAM or establish identity continuity.
- Offline state-machine and response-validation tests passed; real-camera posture accuracy remains unverified. The restarted playground is stopped until the owner starts a rule.

## 2026-10-28 - Prompted live Pi event playground

- Added a standalone playground at localhost:5053 with Pi preview, local sampled-frame SAM masks, and bounded experimental event history.
- Added presence and two-hand movement rules, debounce, freshness checks, duplicate-frame rejection, and stop/discard behavior.
- Added text-only Claude interpretation into supported rules with user review before Start; unsupported conditions are explicit. No model-generated code is executed.
- Live Pi snapshots reached the updated SAM worker. Two hand masks and two_hands_moving/no_two_hand_motion transitions were observed; recent warm requests were approximately 0.6 seconds for this scene.
- Trigger accuracy against intentional gestures remains for owner review. This is not continuous video tracking or a SCADA control connection.
- Credentials and frames remain outside tracked files. No cloud image request or production service change was made.

## 2026-10-28 - Local SAM checkpoint and first inference

- Verified Hugging Face browser login and downloaded the approved SAM 3.1 checkpoint into the Ubuntu cache.
- Corrected the worker's multiplex bucket size to 16 to match the checkpoint; retained an eight-object limit.
- Removed unsupported state offloading and applied the upstream issue 544 / PR 543 session-argument filter through a reproducible runtime patch script, preserving a backup.
- Two checkpoint-backed runs on a generated 640x480 monitor image returned one mask each: 94.49 seconds including loading and 1.55 seconds warm; peak allocated GPU memory reached 5740 MiB.
- These are diagnostic smoke-test results, not camera or tracking benchmarks. No cloud request was made; Meta API setup remains separate.
- All 12 offline segmentation tests passed. Real Pi-photo quality and video tracking remain for testing.

## 2026-10-27 - Project definition and initial structure

- Agreed on a standalone web application outside Ignition Perspective.
- Defined vision and vLock service boundaries and the six development phases.
- Added a beginner-oriented playground plan and experiment report template.
- Made SCADA integration documentation a first-class deliverable.
- Identified the existing vLock Digital LOTO project as pre-existing work.
- Status: documentation/scaffold only. No model requests, service implementation, runtime environment, or performance tests completed.

Future entries should record actual changes, verification evidence, limitations, and next steps. Git history records implementation changes; this log explains their purpose. Do not backfill fictional progress.

## 2026-10-27 - Python environment setup

- Created the project-local Python 3.12 virtual environment.
- Added pinned API SDK, environment loader, and SAM parser dependencies.
- Added playground/check_env.py and docs/SETUP.md with VS Code terminal commands.
- Set Muse Spark and SAM 3.1 identifiers in .env.example; created local .env only if absent.
- Verified dependency imports and pip check; environment checker ran without API calls.
- Credential presence is reported by the local checker; key validity and model access remain unverified.
- No camera, model inference, runtime UI, or local CUDA installation is included.
- Next step after owner review: one-photo Spark scene-analysis experiment.

## 2026-10-27 - Camera playground

- Added playground/camera with a local Python server and browser UI.
- Added generated feed, RTSP/HTTP stream input, preview, disconnect, and explicit JPEG capture.
- Verified generated JPEG frames, capture retrieval, invalid URL rejection,
  cross-origin mutation rejection, stale-frame capture rejection, and disconnect.
- Fixed static-file path resolution found by the initial route check.
- Verified JavaScript syntax and Python dependency consistency.
- Browser verification: generated feed became live and Capture photo displayed a saved JPEG.
- Camera URL is entered locally and held in memory; no API keys or .env values were read.
- Actual IP camera, codecs, latency, Raspberry Pi, USB, ESP32, and multiple cameras remain untested.
- Added docs/CAMERA_SOURCES.md for the owner's Raspberry Pi/USB/multiple-camera/ESP32 targets.
- Next owner review: test the single-camera UI on the PC before extending source support.

## 2026-10-27 - Simplified first local-camera test

- Replaced the network-stream UI and server reader at the owner's request.
- The page now has Start camera, Stop camera, Capture photo, preview, and optional download.
- Browser getUserMedia opens the default PC camera without audio; frames stay in browser memory.
- Removed generated-feed/network endpoints and OpenCV from the camera requirements file.
  Previously installed packages and earlier test captures were not deleted.
- Verified JavaScript syntax, page and asset routes, removal of old API endpoints,
  and visible browser layout. Physical camera permission/video/capture remains for owner testing.
- The local server is running for this review. No model requests were added.
- Raspberry Pi 5 USB capture will be a separate later feed integration, followed by SAM/Muse and prompts.

## 2026-10-27 - Captured-photo Muse analysis

- Added an optional question, explicit Analyze photo action, and plain-text output below the capture.
- Blank question requests a general scene description. The configured Muse Spark cloud API receives only the captured JPEG and question when Analyze is clicked.
- Added analysis.py for the provider request; .env credentials stay in the server process.
- Added upload/prompt limits, same-origin validation, capture identity, loading state,
  sanitized provider failures, and a request timeout without automatic retries.
- Ten offline tests passed for request shape, blank prompts, missing keys, incomplete
  output, sanitized failures, capture identity, upload validation, origin rejection,
  displayable errors, and page/assets. JavaScript syntax and pip check passed.
- No real image/model request was made by the coding agent. Live account access,
  photo answers, and counting accuracy remain for the owner's browser test.
- Current provider is cloud Muse Spark; local model selection and SAM are not implemented.

## 2026-10-27 - Anthropic photo-analysis provider

- Switched the active captured-photo client to the official Anthropic SDK and Messages API.
- Added ANTHROPIC_API_KEY and ANTHROPIC_MODEL example settings; default is claude-sonnet-5-5.
- The private .env file was not edited or displayed. Provider settings reload at analysis time.
- Updated the page disclosure, dependency pin, environment checker, setup instructions,
  image limit (5 MB), and offline request fixtures for Anthropic's image/text block format.
- Ten offline tests and dependency consistency checks passed; no live Claude call was made.
- Owner will add the key locally and test a captured photo using Analyze.

## 2026-10-27 - Claude eye-box output

- Added Box eyes, using a fixed prompt and structured JSON eye coordinates.
- Added a separate annotated canvas with green squares; original capture stays visible.
- Resized the provider image below the standard vision budget and mapped coordinates
  back to the original capture. Validated coordinate types/order/bounds and handled empty detections.
- Fifteen offline Python checks passed, plus JavaScript square/scale/edge checks,
  JavaScript syntax, and dependency consistency checks.
- No personal photo or live Claude request was sent during development.
- Actual eye localization accuracy requires the owner's photo test; SAM/tracking remain unimplemented.

## 2026-10-28 - Pi camera, main UI, and repository migration

- Added the Pi USB MJPEG capture service, latest-frame endpoint, viewer, and boot installer.
- Added the main PC UI with Pi IP entry, JPEG relay, preview, capture, and reconnect handling.
- Owner confirmed both the Pi viewer and the main PC connection work.
- Two Pi-service tests and four main-UI relay tests passed; quantitative hardware latency and reboot testing remain open.
- Created vLock-AI-Vision with a new root commit; no prior Git history was imported.
- Audited every previous tracked and nonignored source/document: none are missing.
- Preserved all README files, architecture and integration plans, workflow notes, experiment template, and historical log entries.
- Preserved portable editor settings and added vLock-AI-Vision.code-workspace.
- Local .env was transferred separately and remains ignored. No secrets or virtual environment are published.
- The owner will handle old repository deletion. vLock-Digital-LOTO remains the separate background project.
- Main UI model integration is the next implementation step; no new live inference was performed during migration.

## 2026-10-28 - Prompted annotations in the main UI

- Added explicit captured-photo Claude analysis to the main Pi camera UI.
- Added general prompts, labeled rectangles, text results, and downloadable annotated images.
- Preserved original captures, capture identity, local secrets, and continuous preview.
- 27 offline tests and dependency checks passed. A generated red-rectangle live request returned matching coordinates in 4.73 seconds.
- No camera photo was sent during development. Real target localization remains for owner review; SAM is the next experiment.

## 2026-10-28 - SAM 3.1 local/cloud experiment

- Added explicit Local GPU / Cloud API selection on the same captured photo.
- Added colored masks, shape-following outlines, image download, backend timing,
  setup status, and local peak allocated VRAM reporting.
- Kept adapters and tests under playground/segmentation. No silent cloud fallback.
- Twelve segmentation/worker tests and thirteen web tests passed using synthetic
  masks and mocked model transport. JavaScript and Python syntax checks passed.
- Installed an isolated Ubuntu/WSL CUDA runtime. CUDA detects the RTX 3070 Ti
  Laptop GPU and the official SAM 3.1 builder imports successfully.
- Started the loopback worker on port 5052 and verified PC-to-worker connectivity.
- At handoff, the cloud key is missing and the local checkpoint is missing.
  No real SAM inference, quality, speed, or 8 GB memory-fit result is claimed.
- Local runtime source revision and dependency caveat are recorded in the
  segmentation README. Owner is arranging Meta key and Hugging Face access.
