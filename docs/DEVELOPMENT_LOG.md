# Development log

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
