# Edge cases

What the app does when things go wrong, and how far each case has been checked.

**Live** ran with real hardware or a real service. **Automated** has a test in the repository. **Simulated** was checked
with a stand-in for the failure. **Not tested** means designed for, but never tried.

## Camera

| Case | What happens | Checked |
|---|---|---|
| Camera gives no fresh frame | `Unknown`, reason `Camera unavailable...`; recovers when frames return | Automated |
| Camera disabled during monitoring | `Unknown`, and the demo's SCADA logic stopped a real printer | Owner-tested |
| A real Pi is unplugged during monitoring | Should behave as above, and recover after the Pi boots | **Not tested** |
| Repeated or out-of-order frames | `Unknown` | Automated |
| Result arrives on an old frame | `Unknown` | Automated |
| Camera resolution changes | `Unknown`; the area must be redrawn | Automated |
| Monitors in view are overexposed | Objects on them wash out. A flag held in front of a bright screen could not be seen by eye | Live, one frame |
| RTSP camera | Implemented | **Not tested** with a real camera |

## SAM on the Meta Model API

| Case | What happens | Checked |
|---|---|---|
| No object in the frame | A real zero, which can be `Clear`. An empty answer is not an error | Live |
| Timeout, connection error, HTTP error | `Unknown`, no retry, and the status is logged | Automated |
| API address unreachable | `Unknown`, reason `Meta SAM unavailable...` | Live, on OPC UA |
| Answer arrives after the limit | Discarded, `Unknown` | Automated |
| Unreadable or incomplete answer | `Unknown`, never zero objects | Automated |
| Key missing | Monitoring won't start, and the status says what to do | Automated |
| Daily spending limit reached | Paid requests stop, and the zone is `Unknown` with a reason saying so. A restart doesn't reset it. Raising the limit or a new UTC day resumes | Automated, plus live |
| Key refused, billing or rate limit error | `Unknown` with the specific reason. One request a minute until fixed; saving a new key tries at once | Automated, plus live with a fake key |
| Meta unreachable or failing repeatedly | `Unknown`, waiting 2 to 30 s between tries, so recovery can take up to 30 s | Automated |
| Spend figure | An estimate that counts requests that may have been billed. Your Meta account shows the real bill | By design |
| Internet cut during monitoring | Should reach `Unknown` through the limit on an open connection | **Not tested** live |
| `api.meta.ai` blocked in the hosts file | **Known limit: stays working.** The app keeps its connection open and a name block doesn't end it. Only a new connection fails | Simulated |

The hosts-file case is not a useful outage test. The reconnect that would change this was deliberately left out for now.

## SAM phrases

| Case | Result | Checked |
|---|---|---|
| `person holding flag`, flag in the hand | Matched the person, score 0.69 | Live, one frame |
| `person holding flag`, flag standing in a holder | No match, which is correct | Live, one frame |
| `person wearing safety vest` | Unknown | **Not tested** |
| Two separate objects, such as `person` and `flag` | Means both are in the area, **not** that one holds or wears the other | By design |
| Rule with a confidence cutoff | None exists. A 0.7 cutoff would have missed the match above at 0.69 | By design |

## Local GPU worker

| Case | What happens | Checked |
|---|---|---|
| Worker crashes | Restarts automatically, up to 3 times in 15 minutes | Live |
| Worker stops answering | Restarted, and the zone is `Unknown` meanwhile | Automated |
| Port 5052 used by another program | Reported, and nothing is stopped | Automated |
| Long-running log | Rotates at 5 MB while the worker runs. Writing to a file the worker holds open failed on Windows, so the app now writes it | Automated, plus a live start |
| Inference stuck | Monitoring can stay "finishing" for up to the 300-second limit | Known limit |
| More than 8 objects of one kind in a frame (6 on Meta video) | `Unknown`, with a reason saying so | Automated, and measured with faked answers |
| Several crowded objects at once | Each mask costs about 0.2 s on the PC. Two objects with many matches each can outlast the 10-second freshness limit, giving a stale `Unknown` | Measured for one object |

## Muse Spark

| Case | What happens | Checked |
|---|---|---|
| Frame-check answer gets old | Reads `stale` after twice the check interval (at least 60 s), keeping its time | Automated |
| Answer returns after monitoring stopped or the rule changed | Dropped | Automated |
| A person asks for something SAM can't confirm alone, such as a helmet | Active still means the SAM rule. The Muse answer is advisory only | Known limit |
| Field names in free-form Muse JSON vary between runs | The app uses a fixed schema for its Muse calls | Live, plus automated |
| Muse leaves the output type on `event` | The rule was right, but `condition` had to be chosen by hand. Check the type before using a proposal | Owner-seen, more testing needed |
| Muse timing | About 4-7 s per call, which is why it stays out of the per-frame path | Live |

## SCADA output

| Case | What happens | Checked |
|---|---|---|
| Any failure | `State` = `Unknown`; `Active` and counts carry Bad quality | Automated, with State and Reason read live over OPC UA |
| Person alone with a person AND dog rule | `Clear`, and the printer kept running | Owner-tested in Ignition |
| Person and a real dog with that rule | `Active`, and a real printer stopped | Owner-tested in Ignition |
| App closed or OPC connection lost | Tags go Bad in the client. The connection showed faulted while OPC UA was off and recovered when it was turned on | Owner-seen in Ignition; the stop on this case is automated only |
| App frozen | Last values stay in place, so SCADA must also watch the heartbeat | Watchdog logic only: automated, not in a real gateway |
| Watchdog reset while quality is Bad | Refused, even just after the last heartbeat | Automated, outside Ignition |
| Script that only checks `Active == True` | Misses camera and cloud loss. It must read `State` | Read from the installed demo script |
| Restart | Old results become `Unknown`. Monitoring doesn't resume by itself | Automated |
| Two-object zone | Both objects are evaluated on the same frame | Automated, live in an independent review, and owner-tested with a person and a dog |

## Application

| Case | What happens | Checked |
|---|---|---|
| Two simultaneous first-setup requests | Exactly one admin is created | Automated |
| Second copy on the same data folder | Refused | Automated |
| Damaged saved file | Moved aside, replaced, and reported | Automated |
| First start with data in the old folder | Copied once, even though the lock file already exists | Automated, plus the real data in a temporary folder |
| Key pasted into the wrong setting | Refused without showing the value on the Setup page. A wrong value in `.env` stops the start with a clear message | Automated |
| Secret on the Setup page | Never returned or written to the audit log | Automated |
| REST token saved on the Setup page | Enforced at once; removing it opens REST again | Automated |
| Typing on the Setup page during a refresh | Text stays. A live check found and fixed this | Live |
| Zone removed | Its saved files are removed, and other zones are untouched | Automated |
| History growth | Held at 1,000 events, about 1.7 MB | Measured, 6,000 writes |
