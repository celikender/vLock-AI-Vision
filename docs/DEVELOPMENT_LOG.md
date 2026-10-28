# Development log

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
