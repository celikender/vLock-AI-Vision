# Camera transport check

Local check on 2026-11-02; original 640 x 480 Pi USB JPEGs, no footage saved.

## Findings

- The Pi health endpoint reported fresh advancing frames. Twelve direct snapshot
  requests had a median of 23.1 ms, maximum 43.4 ms and zero failures. Reported
  Pi frame age in that sample was 1-67 ms.
- The old app relay sample had a median of 42.5 ms and maximum 57.6 ms, with no
  failures. SAM monitoring was enabled at that point. The already loaded CUDA
  worker reported a 2480 ms inference-window time in the workspace snapshot.
- The UI deliberately waited 250 ms between preview requests, limiting preview
  to less than four FPS. Its connected flag also depended on the most recently
  consumed frame. When the dashboard had no preview and SAM was busy, that cached
  frame could age past two seconds despite a healthy Pi stream.

## Implemented change

Explicitly connecting a camera starts one bounded polling worker and one latest
original-JPEG buffer. Preview and SAM read the same latest frame; consumers do not
create extra upstream requests or queues. Network I/O does not hold the camera
status lock. Disconnect/reconnect/removal/app shutdown stops the polling worker.
Real failures clear the buffer, report unavailable, and retry. Sequence/freshness
checks, original JPEG bytes, model sampling and rule freshness limits remain.

Healthy preview requests are paced toward a 50 ms period, matching the earlier
playground's 20 FPS target. Actual rate depends on transport/scheduling. Browser
preview errors no longer overwrite the backend's source-connection status.

After the change, 35 local relay reads had a median of 16.0 ms and maximum 32.1 ms.
The shared stream settled around 14 unique FPS and reported zero failures. The
camera remained connected on the dashboard with no preview open. Monitoring was
off during this after-check, so these samples are not a controlled inference-load
benchmark. No sensor-to-screen latency or full camera hardware limit was measured.

## Initialization and diagnostics

The existing worker remained running and loaded throughout the app restart;
model_loads stayed at one. No new checkpoint, model runtime or inference tuning
was introduced. An initialization message now accompanies the first pending
observation; first-use model/kernel work can take longer, without a guaranteed
warm-up duration. Unknown never becomes Clear merely because initialization ends.

Read-only diagnostics sample the existing worker health, host CPU/memory when
psutil is installed, and NVIDIA GPU name/load/VRAM when nvidia-smi is available.
Sampling runs off the request path. Missing metrics display unavailable. Hardware
loads are host/GPU totals, not model-specific utilization or end-to-end latency.

## Verification

Twelve isolated application/camera checks plus 39 monitoring/state/output checks
passed. Coverage includes a blocked upstream request without blocked cache reads,
freshness with no consumers, failure invalidation/recovery, byte preservation,
stopped workers, saved rules and workspace tag paths. Three browser-side regression
scripts passed. The saved eight-point polygon/configuration hash was preserved;
the owner's off monitoring state was restored. The Pi service and playground
implementations were not modified.
