# One nozzle-temperature test

Experimental terminal reader, separate from the main app and SCADA. Connects to
the printer's local MQTT broker on TLS port 8883, subscribes to its report topic,
prints the first valid `print.nozzle_temper` in Celsius, and disconnects.
Stops after 60 seconds without a reading. Sends no MQTT publishes or machine
control commands, including full-status requests. Missing data is not zero.

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r playground/bambu/requirements.txt
.\.venv\Scripts\python.exe playground/bambu/read_temperature.py
```

Uses BAMBU_IP, BAMBU_SERIAL, and BAMBU_ACCESS_CODE from this terminal's environment.
Prompts for missing settings; access-code input is hidden. Settings stay in memory.
Uses Python 3.12 and downloads public Bambu CA certificates over HTTPS at startup;
this test requires internet access for that download. Printer settings are not sent
to the certificate host. TLS checks the certificate chain and printer serial.

Expected milestones: TLS verified and MQTT authentication accepted, subscription
accepted, then a numeric nozzle temperature. A reachable TCP port alone does not
prove any of these. P1 delta reports may omit temperature; a timeout does not
establish that authentication failed. Keep the firmware and printer mode unchanged
for the initial reading attempt.

Protocol and certificate references:
- https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- https://github.com/Doridian/OpenBambuAPI/blob/main/tls.md

Live authentication and temperature reading remain unverified until run against
the owner's printer. This is not yet a SCADA integration.
