# SAM 3.1 segmentation playground

## Dynamic camera-video prompting

Run the existing worker and playground monitor in separate PowerShell terminals:

```powershell
.\playground\segmentation\start_local.ps1
```

```powershell
.\.venv\Scripts\python.exe playground/segmentation/monitor.py
```

Open http://localhost:5053, enter the Pi address and port, select **Prompted video
tracking**, and enter `person`, `forklift`, `conveyor belt`, or another object
phrase. Start monitoring. Edit the phrase and click **Apply video prompt** while
it runs. This mode calls local SAM directly; no interpretation/model service is
needed to prepare the phrase. Existing sampled-frame rules remain available.

Root cause: the previous camera loop created a one-JPEG session, sent `add_prompt`,
and immediately closed it. It never called `propagate_in_video`, and the UI locked
the phrase during monitoring. The GPU model itself already supported text prompts.

Compatibility was inspected in the installed `sam3` distribution (package version
0.1.0, source revision `f1647e8d0c1d280991f4d1b7d974c2704537fe66`), using the
`build_sam3_predictor(version='sam3.1', ...)` multiplex predictor. See the
[official request dispatcher at that revision](https://github.com/facebookresearch/sam3/blob/f1647e8d0c1d280991f4d1b7d974c2704537fe66/sam3/model/sam3_base_predictor.py).
The existing checkpoint, builder options, bf16 inference and runtime session fix
are retained. No runtime package or camera decoder was changed.

### Camera windows and session boundaries

The installed loader enumerates a finite file/directory at session creation. It
does not expose an append-camera-frame request. The playground therefore collects
exactly four fresh original JPEGs at up to four samples/second when ready, writes
them unchanged to a temporary numbered directory, starts one video session, sends:

```python
predictor.handle_request(request={
    'type': 'add_prompt', 'session_id': session_id,
    'frame_index': 0, 'text': user_prompt,
})
for result in predictor.handle_stream_request(request={
    'type': 'propagate_in_video', 'session_id': session_id,
    'propagation_direction': 'forward', 'start_frame_index': 0,
    'max_frame_num_to_track': 4,
}):
    process_frame(result)
```

The session stays alive throughout propagation and closes on completion, failure,
or stream cancellation; its temporary JPEGs are removed. Each new window starts
a new session. **IDs are stable within a session only.** Use `(session_id,
object_id)` or `track_id`; an ID in another window is not proof of the same object.
This is sampled camera video with finite-window tracking, not uninterrupted
identity tracking or real-time inference. The Pi latest-frame transport and
independent preview are unchanged; there is no growing backlog of video frames.

Applying a new phrase increments a prompt revision, immediately clears old visible
results and resets observation state. Any in-flight GPU computation may finish,
but its old-revision results are discarded. The stream/session is closed at the
next output boundary and fresh camera frames start a new session with the new
text. Stop uses the same discard/cleanup behavior. These operations reuse the
worker's already loaded predictor. `/health` includes `model_loads` for checking.

### Per-frame JSON and debug output

The worker accepts bounded multipart camera windows at `POST /video/track` and
streams `application/x-ndjson`, one `type: frame` row per propagated frame. A
stream-time failure is a `type: error` row, never an empty detection/clear zone.
The monitor exposes `GET /api/video/results?after=OUTPUT_ID` with the latest eight
frame rows and cursor/retention metadata. Poll often enough; older rows are
discarded. `/api/status` includes the last processed overlay. Prompt updates use
`POST /api/prompt` with `{"prompt":"forklift"}` from the same-origin page.

Each frame includes prompt/revision, SAM session ID, window frame index, original
camera sequence, dimensions, object count, and `objects` containing:

- `object_id` and session-qualified `track_id` from SAM, never list position IDs.
- `bbox_xywh` in normalized image coordinates, as supplied by SAM.
- `score` from SAM's `out_probs`; null if unavailable. This is the available model
  score, not a calibrated per-frame tracking-quality estimate.
- `mask`: lossless uncompressed COCO RLE, with `size: [height,width]` and integer
  `counts`, traversed column-major, beginning with a background run. The helpers
  in `video_tracking.py` encode/decode this format.

Frames also expose elapsed window processing time, peak allocated GPU memory,
model load count, and observation age/staleness. Initial load may make a window
stale; stale results cannot establish object absence. Age is refreshed when
reading the monitor JSON history.

The worker terminal logs the exact JSON `add_prompt` text and propagation request,
then actual output IDs, boxes, scores, mask dimensions and run counts. Complete
mask arrays are represented losslessly in the HTTP JSON rather than dumped into
the terminal. Exceptions retain a worker traceback.

### Verified camera test — 2026-10-28

Live Pi video at 640×480 returned all four frames of each tested session. Two
`person` windows returned object ID 0 with nonempty masks and available scores
(including 0.859649 in the warm window). Changing to `forklift` during the same
monitoring run returned four empty-object frames. This verifies prompt forwarding
and no-target output, not forklift recognition accuracy against an actual forklift.
All 12 published frames reported `model_loads: 1`. Initial window processing took
45.25 seconds and was marked stale; warm windows took 7.96 seconds for `person`
and 6.08 seconds for `forklift`. Peak allocated tensor memory reached 8215 MiB;
these measurements are not sensor latency or evidence of real-time throughput.
Detection/identity accuracy remains for visual owner review.

Reproduce explicitly against your camera after starting both servers:

```powershell
.\.venv\Scripts\python.exe playground/segmentation/video_smoke.py --address 192.168.1.254:8080 --output playground/outputs/video_prompt_smoke.json
```

This test starts video monitoring, collects two person windows, changes the active
prompt to forklift, verifies all frame indices and one unchanged model-load count,
and stops monitoring. Full per-frame JSON stays in the ignored output directory.
The smoke test refuses to interrupt an existing active monitor. Offline checks
also cover exact masks, stream cleanup, invalid input, model reuse, and discarding
in-flight results after a prompt change.

## Live Pi event playground

Claude prepares a rule from text. Local SAM processes all camera images. The
monitoring loop has no Claude image-analysis path. Earlier stand-up cloud code
is retained as an inactive experiment; stand_up requests are rejected by this server.

From two PowerShell terminals in the project folder:

```powershell
.\playground\segmentation\start_local.ps1
```

```powershell
.\.venv\Scripts\python.exe playground/segmentation/monitor.py
```

Open http://localhost:5053, enter the Pi IP and port, and describe an event:
"Trigger when both hands are above my head and moving." Choose Prepare rule with
Claude, review the SAM concepts and comparisons, then Start local SAM monitoring.
Only setup text goes to Claude. Manual selection works without a Claude call.

Implemented rules:
- Object presence: local SAM segments one prompted concept; two fresh observations
  confirm present or absent.
- Two hands moving: local SAM segments hand and compares the two largest mask centers.
- Both hands above head and moving: local SAM segments hand, head, and person on
  the exact same JPEG, sequentially with the same loaded model. Requires exactly
  two hand masks, one head, and one person. Hand/head centers must lie within the
  person mask's bounding box. Entire hand boxes must be above the head box's top
  edge with a 1% normalized frame-height margin. Both hand centers must move at
  least 4% relative to the head across two consecutive comparisons. Nearest-center
  pairing handles output ordering; jumps above 30% and major person-box changes
  reset the movement baseline. Emits both_hands_raised_moving on activation and
  raised_hand_motion_inactive when confirmed inactive.

These are experimental geometric rules, not body-joint estimation, identity
verification, or general action recognition. Use one person and a fixed camera.
Occlusion, multiple people, or missing masks produce unknown. Hand masks are
shown on the processed image; head/person detection counts are shown underneath.

Preview and inference are independent. A new original JPEG is fetched only when
SAM is ready; frames are not queued. Each result retains its camera frame sequence.
Duplicate, failed, or older-than-10-second observations cannot establish absence.
Cold loading can make the first result too old to use. Three concept requests take
longer than the earlier single-concept timing. These geometric rules do not use
the separate video-tracking mode above. Stop discards in-flight results; closing
the page does not stop it.

GET /api/status exposes the latest result and up to 100 in-memory events with IDs,
run IDs, rules, frame sequences, UTC publication times, and experimental flags.
No webhook, SCADA command, worker lock, or production vLock state is changed.

Verification: offline geometry, event, stale-data, cancellation and interpretation
checks pass. Text-only Claude preparation returned the three correct SAM concepts.
Earlier live testing confirmed hand segmentation and movement events; raised-hand
accuracy and physical ownership/correspondence still require owner review.

## Captured-photo flow

In the main PC app, Capture photo, scroll to SAM 3.1 experiment, select Local GPU
or Cloud API, enter one object phrase (for example monitor), and click Segment.
Both modes use the same capture, reduced to a maximum edge of 1008 pixels.
Results show colored pixel masks with outlines, object count, elapsed time, and
an annotated PNG download. The original capture and Claude result remain visible.
These are model predictions, not exact geometric measurements or tracking.

## Cloud API

In the root local .env set META_API_KEY to your Meta developer API key and
META_SAM_MODEL=sam-3.1. Settings reload per request. No key goes to the browser.
MODEL_API_KEY is accepted as an alternative. The endpoint is fixed to Meta's API.
Cloud mode sends the selected JPEG and prompt to Meta only when Segment is clicked.
Use Check setup to see key presence; presence does not verify account access.

## Local GPU on Windows through Ubuntu/WSL

The local worker runs separately from the PC UI, on loopback port 5052.
The isolated Python environment is ~/.local/share/vlock-vision/sam-env inside Ubuntu.
The model cache uses Hugging Face's default user cache; neither location is tracked.

After obtaining approval at https://huggingface.co/facebook/sam3.1, open Ubuntu:

```bash
~/.local/share/vlock-vision/sam-env/bin/hf auth login
~/.local/share/vlock-vision/sam-env/bin/hf download facebook/sam3.1 sam3.1_multiplex.pt
```

Enter credentials only into your terminal, never chat or source files.
Then run from the project PowerShell terminal:

```powershell
./playground/segmentation/start_local.ps1
```

Keep that terminal open. In the app select Local GPU and Check setup.
The first segmentation loads the model; later requests reuse it. The worker uses
the official SAM 3.1 predictor on a temporary one-frame session, bf16 inference,
eight tracked objects with the checkpoint's required 16-slot multiplex bucket,
CPU frame offloading, no compilation, and no Flash
Attention 3 dependency. Temporary captures are removed when the request finishes.
Grounding processes one frame per batch on the existing 8 GB GPU. This bounds
temporary activations while retaining the checkpoint's 16-slot multiplex bucket,
input resolution and confidence settings. Startup logs report the grounding batch
size. A matched-frame comparison against batch sizes 16 and 2 measured lower
latency and memory for size 1, with matching counts/IDs/boxes/scores and near-identical
masks on the test clip. See the [performance report](../reports/monitoring_performance.md).
Local images are not uploaded. Local failure never switches to cloud automatically.
An 8 GB GPU may still run out of memory; the UI reports that explicitly. Do not
claim a latency or memory result until a real checkpoint-backed run succeeds.
Peak VRAM reports allocated GPU tensor memory, not total system GPU usage.
Cloud and local elapsed timings include their respective request/processing costs;
the local first call includes model load and is not comparable to a warm run.

## Reproduce runtime setup

Install python3.12-venv, git, libgl1, and libglib2.0-0 through Ubuntu apt first.
Create the isolated environment and install official PyTorch CUDA wheels:

```bash
python3 -m venv ~/.local/share/vlock-vision/sam-env
~/.local/share/vlock-vision/sam-env/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'setuptools<81' pillow flask einops psutil opencv-python-headless==4.11.0.86 pycocotools scipy==1.15.3 decord
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'git+https://github.com/facebookresearch/sam3.git@f1647e8d0c1d280991f4d1b7d974c2704537fe66'
```

Official references: [model repository](https://github.com/facebookresearch/sam3),
[cloud API](https://dev.meta.ai/docs/sam/overview),
[parser](https://dev.meta.ai/docs/sam/client-libraries).

## Verification

Run `python -m unittest discover -s playground/segmentation -p 'test_*.py' -v`
in the PC environment. Tests use synthetic masks and mocked API transport.
They cover geometry, overlay output, invalid responses, missing keys and backend
separation. Live account access, checkpoint compatibility, segmentation quality,
and GPU memory fit require real inference and are separate from these checks.
## Installed-runtime check

CUDA detects the RTX 3070 Ti Laptop GPU and the SAM 3.1 builder imports successfully.
The older decord 0.6.0 wheel imports successfully but pip check reports an unsupported-platform warning.
Checkpoint-backed inference passed on 2026-10-28 using a generated 640x480 monitor
image: one mask, 94.49 seconds including load, then 1.55 seconds warm, with peak
allocated GPU tensor memory of 5740 MiB. These diagnostic-run timings are not a
camera benchmark. Real-photo quality and video tracking remain unverified.

## Session compatibility fix

The pinned runtime has the upstream start-session argument bug described in
[issue 544](https://github.com/facebookresearch/sam3/issues/544) and
[proposed fix 543](https://github.com/facebookresearch/sam3/pull/543).
Apply the reproducible argument-filtering patch from Ubuntu, using the project path:

```bash
~/.local/share/vlock-vision/sam-env/bin/python '/mnt/c/Users/ec-en/Desktop/vLock-AI Vision/playground/segmentation/patch_runtime.py'
```

The script preserves the original runtime source beside the patched file and
refuses unexpected source layouts. Re-running it reports an already installed fix.
SAM 3.1 does not support state offloading through this session interface.
