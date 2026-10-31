# SAM 3.1 monitoring performance pass — 2026-10-29

Implemented three bounded optimizations in the existing playground adapters. The
checkpoint, 16-slot multiplex architecture, 1008 model input, bfloat16 inference,
confidence settings, CUDA packages, camera decoding, polygon logic, persistence,
warning events, and 10-second capture-age freshness limit are unchanged.

## Grounding batch comparison

Used the same four original 640×480 camera JPEGs for every run, with fresh SAM
sessions and one loaded model. Tested the default grounding batch size 16 and
candidates 1 and 2, in order 16/1/2 then 2/1/16, after an untimed warmup. Each size
processed two repetitions of three prompts: `plastic storage drawers` (visible
target), `person`, and `forklift` (no-target controls). Total: 18 requests, 72
returned frame results. This is a small regression comparison, not an accuracy
dataset or a test of forklift recognition.

| Grounding batch size | Median request through cleanup | Median first result | Peak allocated tensor memory | Peak reserved allocator memory | Frames/s, excluding collection/UI |
|---|---:|---:|---:|---:|---:|
| 16, previous default | 5.93 s | 5.65 s | 8,215 MiB | 9,104 MiB | 0.67 |
| **1, selected** | **2.80 s** | **2.71 s** | **6,585 MiB** | **6,884 MiB** | **1.39** |
| 2 | 3.89 s | 3.73 s | 7,595 MiB | 7,998 MiB | 1.01 |

Batch size 1 reduced median request time by 53% and peak tensor allocation by
20%. Physical adapter counters also improved: shared usage peaked at 1.94 GiB
with batch 16, 0.88 GiB with batch 2, and 0.253 GiB with batch 1 (near the sampled
background shared usage). These are adapter-wide residency counters, not tensor
allocation or exclusive per-process memory. No GPU migration trace was captured.

Counts and object IDs matched in every compared frame. Boxes and available
scores matched exactly. Minimum positive-mask intersection-over-union was
99.9888% for batch 1 and 99.9944% for batch 2, relative to batch 16. Small mask
differences occurred despite unchanged weights/precision settings; results are
not claimed to be bit-identical. Maximum polygon-overlap-ratio difference was
0.0000561. Every matched-frame condition result and persistence state sequence
matched the baseline, including Unknown → Warning on the visible target.

The selected setting is `GROUNDING_BATCH_SIZE=1` in local_worker.py and is applied
to the installed model's `batched_grounding_batch_size` attribute after building
the same predictor. Startup logs include the actual setting. This changes the
number of frames grounded together, not the checkpoint's multiplex capacity.
The worker refuses a runtime that lacks this setting rather than silently
pretending the optimization was enabled.

## Collection and overlay changes

- The controller waits 250 ms only when another camera sample is needed. It
  retains spacing between samples and retries duplicates; it no longer waits
  after accepting frame four. Three real-camera collection trials per version
  measured median 1.141 s before versus 0.904 s after: approximately 237 ms saved.
- Every propagated frame still runs mask/polygon evaluation, persistence,
  state/event updates, and JSON/mask retention. Only frame 3 generates the UI
  overlay. Earlier frame results remain available through the existing results
  API. Until the newest overlay is ready, the previous UI observation retains
  its own image, metadata, and capture age.
- Replaying identical real masks and JPEGs through publication measured median
  251 ms before versus 68 ms after per window (eight repetitions per version).
  Non-timing history fields were equal, including every mask, overlap result,
  output sequence, and rule state. The newest UI image was still frame 3.

## Live before/after check

Hardware: the existing RTX 3070 Ti Laptop GPU with 8 GiB dedicated memory, the
existing WSL CUDA environment, and the same Pi feed. Both runs used the saved
`hand` prompt, 640×480 JPEGs, saved polygon, 10% overlap, 0.25-second persistence,
and warning action. Before: 120.03 s. Final after: 120.10 s on the normal worker
with its usual prompt/output logs enabled. Cold startup was warmed separately.

| Metric | Before | After |
|---|---:|---:|
| Published frames / completed four-frame windows | 56 / 14 | 124 / 31 |
| Actual delivered processing FPS | 0.47 | 1.03 |
| Median worker elapsed before output | 6.26 s | 2.70 s |
| p95 worker elapsed before output | 11.64 s | 2.78 s |
| Peak allocated tensor memory | 8,171 MiB | 6,528 MiB |
| Median GPU busy utilization | 100% | 85% |
| Sampled peak physical device memory used | 7,987 MiB | 7,430 MiB |
| Median capture-to-delivery age | 7.30 s | 3.35 s |
| Median displayed observation age | 11.35 s | 4.69 s |
| Maximum displayed observation age | 22.04 s | 6.71 s |
| Stale samples among samples with a result | 68/107, 63.6% | 0/116, 0% |
| API errors during observation | 0 | 0 |

The scene changed between live runs: before had 36 empty and 20 one-object frame
results; after had 124 empty results. Do not interpret this as a controlled
positive-detection speed or accuracy comparison. The matched-frame experiment
above controls scene content and includes positive masks. The after run was
Unknown for its first four status samples while waiting for observations, then
Normal for 116; missing observations were not counted as fresh.

Worker elapsed is cumulative request/session processing through output, not a
single-frame CUDA kernel timer; it excludes later cleanup. FPS includes camera
collection, inference, publication, cleanup, and window gaps. Ages use existing
software capture metadata plus request timing, with API polling delay. Sensor
exposure, USB buffering, and browser paint were not separately instrumented.

## Accuracy, warnings, and preservation checks

- The normal optimized worker processed the visible drawers under the real
  saved polygon and reached Warning with `warning_active=true`; changing the
  active target to `forklift` returned four empty-object results and Normal with
  `warning_active=false`. The final check's latest observation ages were 3.54 s
  and 2.86 s. Both overlays decoded as 640×480 PNGs tied to analyzed frame 3.
- Every phase returned all four frame indices, lossless RLE masks when detected,
  IDs, boxes, available scores, and polygon measurements. Model load count stayed
  at one across repeated requests and prompt changes within each worker process.
- The initial worker was stopped for the isolated comparison to avoid two GPU
  models competing for memory. The comparison model loaded once for all batch
  trials. The normal worker was then restarted to activate the selected default
  with standard logging and was reused for the final checks. These deliberate
  process restarts are not per-window checkpoint reloads.
- Saved configuration hashes matched before/after each live run and after the
  temporary warning-test prompt changes. The original `hand` prompt was restored;
  monitoring was restored to stopped. Normal local monitoring events were added.
- 99 offline tests passed: monitoring 19, segmentation 43, web 16, camera/photo
  19, Pi camera service 2. JavaScript syntax and Git whitespace checks passed.
  Existing stale/future/duplicate-frame, prompt-cancellation, mask geometry,
  inside/absence, persistence, warning/event-only, and model-reuse checks remain.
  New regressions cover removing the final wait without losing frame uniqueness,
  retaining every mask/rule result while rendering one overlay, and keeping old
  observations stale.

No broader recognition-accuracy claim is established: positive person/hand and
real forklift scenes, occlusion, multiple objects, threshold-boundary masks, and
long-duration memory behavior still require representative footage. No new
resolution, confidence, precision, or hotstart setting was introduced to obtain
these results.

## Remaining bottlenecks and run commands

Four-frame sessions still buffer outputs until propagation finishes, reset IDs
at each window boundary, and incur collection, prompt, and cleanup costs. The
1008 model input and eager GPU computation remain. This pass improves sampled
monitoring; it does not establish continuous tracking or camera-rate inference.
The final normal-worker cold warmup request took 99.25 seconds including model
load, first inference, and first cleanup; startup latency remains outside this
warm optimization. Old startup observations remain unusable for rule decisions.

Start from the project folder in two PowerShell terminals:

```powershell
.\playground\segmentation\start_local.ps1
```

```powershell
.\.venv\Scripts\python.exe web/server.py
```

Open http://localhost:5051/monitoring and explicitly start the saved rule.
Existing tests can be run using the commands in the monitoring and segmentation
READMEs. Private camera clips, full mask JSON, telemetry, and diagnostic harnesses
are retained only under ignored playground/outputs/performance_pass/. Its
summary.json indexes the measurements; batch_runs.json and batch_comparisons.json
contain matched-frame evidence; before/ and after_normal/ hold the final live
comparison. No private footage or model files are published with this report.
