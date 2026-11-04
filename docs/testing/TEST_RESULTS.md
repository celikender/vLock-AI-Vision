# Test results

Measured on Windows with an RTX 3070 Ti Laptop GPU, a Pi 5 USB camera at 640x480 and one room, November 3, 2026, unless noted.
These are small samples that show the system works and how fast. They are **not** an accuracy benchmark or a long-duration
test. For behavior under failure, see the [edge cases](EDGE_CASES.md).

## Not verified yet

- **Ignition:** the UDT and tag import, the fixed tags in a gateway, Ignition reading the `nsu=` paths, the example latch, and the
  heartbeat watchdog in a real gateway.
- **The full chain:** this app to Ignition to a machine. An earlier experiment paused a real printer through Ignition, using an
  older tag path.
- **Real failures:** unplugging a Pi during monitoring, and a real internet cut.
- **Detection:** a safety vest phrase, accuracy on plant footage, and matches through the full app on the Meta video engine.
- **Setups:** Docker with the Meta engines, RTSP cameras, MQTT with a real broker, a second PC on OPC UA, Linux hosts, a separate clean PC.
- **Duration:** long runs.

## SAM engines

| Engine | Sample | Time | Notes |
|---|---|---|---|
| Local GPU, 4 frames | One check per run | 3.0-3.9 s | First model load 68-104 s |
| Local GPU in Docker, 4 frames | 6 checks | Median 3.13 s, one 6.28 s outlier | |
| Meta image, 1 frame, through the app | 32 requests on changing frames | 375-1,625 ms, average 746 ms | None over the 3-second limit. Scores changed between frames, so results were not cached |
| Meta video, 4 frames, through the app | 13 requests | 1,187-2,407 ms, average 1,800 ms | No objects matched in this run |
| Meta video, 4 frames, direct | 3 requests | 1,587-2,886 ms | All 4 frames returned, `person` at 0.88, billed 50 frames each |

**Cost at these rates, per object while monitoring:** Meta image up to about $9 an hour at one check a second. Meta video about
$14 an hour at 12 requests in 30 seconds. Prices are Meta's listed $2.50 per 1,000 images and $0.20 per 1,000 video frames, with
a 50-frame minimum per request.

## SAM phrases on the Meta API, single frames

Each phrase ran 5 or 10 times on one frame, with identical scores on every run of a frame.

| Frame | Phrase | Matched | Score | Average time |
|---|---|---|---|---|
| Person seated | `person` | Yes | 0.96 | 930 ms |
| Person seated | `monitor` | 2 of 2 | 0.72, 0.64 | 645 ms |
| Flag in a holder | `flag` | Yes | 0.93 | 1,019 ms |
| Flag in a holder | `person holding flag` | No (correct) | | 739 ms |
| Flag in the hand | `person holding flag` | Yes, the person | 0.69 | 887 ms |
| Flag in the hand | `flag` | Yes | 0.75 | 947 ms |
| Flag in the hand | `person` | Yes | 0.95 | 824 ms |
| Desk, no person | `person`, `dog` | None (correct) | | 513 ms, 874 ms |
| Desk, no person | `storage drawers` | Yes | 0.69 | 780 ms |

## Crowded scenes

Through real monitoring code with Meta's answers faked, so this measures the PC and not the network.

| Engine | Objects | Time to confirm |
|---|---|---|
| Meta image | 8 | 5.0 s |
| Meta image | 16 | Never, within 28 s |
| Meta video | 2 per frame | 2.8 s |
| Meta video | 4 per frame | 4.5 s |
| Meta video | 6 per frame | 6.2 s and 9.0 s in two runs, close to the 10-second freshness limit |
| Meta video | 8 per frame | Never, within 28 s |

So the limits are 8 objects on the image and local engines and 6 per frame on video. Above them the zone is `Unknown`, with a reason saying so.

Each mask costs about 0.2 s of CPU to parse and convert. That time is included in the Meta times above.

## Spending limit and backoff

Real Meta calls and real monitoring code, with a saved camera frame instead of the Pi.

| Test | Result |
|---|---|
| Fake key, 12 s | 1 refused request, with the reason `Meta rejected the API key...`. No spend counted |
| Real key, 1-cent limit, 12 s | Exactly 4 requests, then `Unknown` with the limit reason |
| Restart at the same limit, 5 s | No requests. The spend was kept |
| Limit raised to 2 cents, 12 s | 4 more requests, then stopped again |

The spend figure is an estimate. It has not been compared with Meta's actual bill.

## Muse Spark

| Test | Result |
|---|---|
| Image question, 10 runs | 3,807-7,238 ms, average 5,699 ms. Correct "no" every time, but field names varied without a schema |
| Text-only rule proposal, independent review | 6.03 s |

## SCADA output

| Test | Result |
|---|---|
| OPC UA with `meta_api`, read by a separate client, not Ignition | `State` and `Reason` changed correctly. The heartbeat moved 13 in 12 s |
| Every node named in the tag export | All 26 exist |
| Unreachable API address over OPC UA | `State` = `Unknown`, with the Meta reason, within about a second of reading |
| OPC UA from Windows through Docker | Person detected, zone Active, `Count1` = 1 |
| REST and OPC UA, independent review | Values agreed, and OPC UA rejected a write |
| MQTT, independent review, isolated broker | Delivery, stale and null state, and offline availability passed |

## Recovery

| Test | Result |
|---|---|
| Local worker restart in Docker | Ready at 59 s. The zone stayed Unknown until Active at 67 s, with no manual step |
| Stopping during real inference, independent review | Output invalidated, and completed work discarded |

## Storage

| Test | Result |
|---|---|
| 6,000 writes to the observation database | 1,000 events and about 1.7 MB from 2,000 writes onward; 6.2 ms per write |

## Camera

Pi camera streaming measured about 11-16 fps in live runs. See [camera performance](CAMERA_PERFORMANCE.md).

## Automated suites

Run from the repository root:

| Suite | Tests | Command |
|---|---|---|
| Services | 165 | `python -m unittest discover -s services -p "test_*.py" -t .` |
| Web | 33 | `python web/test_application.py` |
| Ignition package | 19 | `python -m unittest ignition/test_ignition_package.py ignition/test_heartbeat_watchdog.py` |
| Pi camera | 3 | `python -m unittest discover -s demo_site/pi_camera -p "test_*.py"` |
| Printer project | 7 | `python demo_site/printer_ignition/test_project.py` |
| UI scripts | 3 | `node web/test_zone_workspace.cjs`, `web/test_camera_preview.cjs`, `web/test_analyzed_preview.cjs` |

The Ignition scripts run outside Ignition, with a stand-in for its `system` module.
