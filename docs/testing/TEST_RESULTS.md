# Test results

Measured on Windows with an RTX 3070 Ti Laptop GPU, a Pi 5 USB camera at 640x480 and one room, November 3, 2026, unless noted.
These are small samples that show the system works and how fast. They are **not** an accuracy benchmark or a long-duration
test. For behavior under failure, see the [edge cases](EDGE_CASES.md).

## Full chain, owner-tested

Run by the project owner on November 4, 2026: Pi camera, this app, OPC UA, real Ignition with the imported fixed tags, the demo's
customer-side stop logic, and a real Bambu P1S printer. These were observed by hand, so no times were measured.

| Test | Rule in use | Result |
|---|---|---|
| Person alone in the area | Person AND dog | `Clear`, and the printer kept running |
| Person holding a real dog in the area | Person AND dog | `Active`, and the printer stopped |
| Hand and a water bottle both in the area (demo video) | Hand AND bottle | `Active`, and SCADA paused the printer. Owner-observed; recorded in the development log on November 4, 2026 |
| Camera disabled | | `Unknown`, treated as a stop, and the printer stopped |
| Local GPU and Meta cloud engines | | Both worked. Switching from local to Meta needed an app restart, which is the current design |
| Muse setup | | Rule set up correctly, but the output type stayed `event`. With `condition` chosen by hand, the output worked as planned |

The owner also reports that the SCADA side and the camera side work overall. The app itself only published status; the stop came
from the SCADA side, whose demo logic sends the printer a Pause.

## Not verified yet

- **Reference scripts:** `ignition/stop_latch_example.py` and `ignition/heartbeat_watchdog.py` in a real gateway. The demo uses its own
  logic in `demo_site/printer_ignition/`.
- **Real failures:** unplugging a Pi during monitoring, and a real internet cut.
- **Muse:** its proposals need more detailed testing across more prompts.
- **Detection:** a safety vest phrase and accuracy on plant footage. Which Meta engine, image or video, ran in the owner's test was not
  recorded, so a match through the full app on the video engine isn't confirmed.
- **Setups:** Docker with the Meta engines, RTSP cameras, MQTT with a real broker, a second PC on OPC UA, Linux hosts, a separate clean PC.
- **Duration:** long runs.

## SAM engines

**Time per check, seen by the owner in the running app on November 4, 2026.** These are the realistic figures:

| Engine | Time per check |
|---|---|
| Meta image | 2-3 s |
| Local GPU | 4-5 s |
| Meta video | 8-17 s |

At those times Meta video can outlast the freshness limit, so the zone went `Unknown` between clips and SCADA stopped. Raising the
observation time from 15 to 30 s let it run. It is too slow for this use today.

**Earlier measurements.** Small samples, some with nothing matched, and mostly the request time alone, so they are faster than the
figures above:

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

Run from the repository root, after `pip install -r requirements-test.txt`. Without the two extra packages in that
file, four tests in the Services suite are skipped.

| Suite | Tests | Command |
|---|---|---|
| Services | 166 | `python -m unittest discover -s services -p "test_*.py" -t .` |
| Web | 33 | `python web/test_application.py` |
| Ignition package | 20 | `python -m unittest ignition/test_ignition_package.py ignition/test_heartbeat_watchdog.py` |
| Pi camera | 3 | `python -m unittest discover -s demo_site/pi_camera -p "test_*.py"` |
| Printer demo | 79 | `test_project.py`, `test_site_logic.py`, `test_bundle.py`, `test_connector.py` in `demo_site/printer_ignition/` |
| UI scripts | 3 | `node web/test_zone_workspace.cjs`, `web/test_camera_preview.cjs`, `web/test_analyzed_preview.cjs` |

The Ignition scripts run outside Ignition, with a stand-in for its `system` module.

None of these suites needs a camera, a GPU, an API key or an Ignition gateway. `.github/workflows/tests.yml` runs them
on every push and pull request. On November 10, 2026 the Python suites passed in a fresh Ubuntu 24.04 copy with Python
3.12 on this PC, and the UI scripts on Windows. The workflow itself has not run on GitHub yet.
