Site notes (edit for your plant):
- Cameras: Raspberry Pi 5 USB camera (640x480) and RTSP IP cameras (sub-stream preferred).
- GPU: one RTX 3070 Ti Laptop (8 GB). A SAM check takes about 3 s per object; two-object
  zones need a result expiry of 15 s or more.
- Output names: lowercase words with underscores, area code last, for example
  person_in_area_A101.
- Unknown is never Clear. SCADA must also watch Bridge/Online and the heartbeat.

Measured on this site (small samples, one camera):
- SAM time: local GPU 3-3.9 s for four frames; Meta image about 0.75 s per frame; Meta video about 1.8 s for four frames.
- Scores: person 0.95-0.96; flag 0.75-0.93; monitor 0.64-0.72 (overexposed screens); storage drawers 0.69; hand 0.70-0.79.
- "person holding flag" matched at 0.69 when held, and found nothing with the flag in a holder (two frames only). "wearing" phrases are untested.
- "person" AND "dog" as two objects worked with a real dog: a person alone stayed Clear, and both went Active.
- Prefer simple nouns as separate objects. Two objects means both are in the area, not holding or wearing.
- Bright screens wash out this camera; objects in front of them may not be found.
