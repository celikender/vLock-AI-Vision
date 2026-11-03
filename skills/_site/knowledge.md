Site notes (edit for your plant):
- Cameras: Raspberry Pi 5 USB camera (640x480) and RTSP IP cameras (sub-stream preferred).
- GPU: one RTX 3070 Ti Laptop (8 GB). A SAM check takes about 3 s per object; two-object
  zones need a result expiry of 15 s or more.
- Output names: lowercase words with underscores, area code last, for example
  person_in_area_A101.
- Unknown is never Clear. SCADA must also watch Bridge/Online and the heartbeat.
