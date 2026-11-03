"""One local MQTT subscription: print one nozzle temperature, then exit."""

import getpass
import ipaddress
import json
import math
import os
import ssl
import time
from urllib.request import urlopen

import paho.mqtt.client as mqtt


CA_URL = "https://raw.githubusercontent.com/Doridian/OpenBambuAPI/main/examples/ca_cert.pem"


class PrinterTLSContext(ssl.SSLContext):
    """Connect to an IP while checking the certificate against the serial."""

    def wrap_socket(self, *args, **kwargs):
        kwargs["server_hostname"] = self.printer_serial
        return super().wrap_socket(*args, **kwargs)


def setting(name, label, hidden=False):
    value = os.environ.get(name, "").strip()
    if not value:
        value = (getpass.getpass(label) if hidden else input(label)).strip()
    if not value:
        raise ValueError("Missing " + name)
    return value


def main():
    host = setting("BAMBU_IP", "Printer IP: ")
    ipaddress.IPv4Address(host)
    serial = setting("BAMBU_SERIAL", "Printer serial: ")
    if not serial.isascii() or not serial.isalnum():
        raise ValueError("Printer serial must contain only letters and digits.")
    access_code = setting("BAMBU_ACCESS_CODE", "Printer access code (hidden): ", True)

    print("Loading public Bambu CA certificates over HTTPS...")
    # Only public CA data is fetched. No printer settings are sent to this URL.
    with urlopen(CA_URL, timeout=10) as response:
        ca_data = response.read(32768).decode("ascii")
    context = PrinterTLSContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.printer_serial = serial
    context.load_verify_locations(cadata=ca_data)

    state = {"temperature": None, "error": None, "messages": 0}
    topic = f"device/{serial}/report"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set("bblp", access_code)
    client.tls_set_context(context)
    client.connect_timeout = 10

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            state["error"] = "MQTT authentication rejected. Check the current access code and printer mode."
            return
        print("TLS verified. MQTT authentication accepted.")
        result, _ = client.subscribe(topic, qos=0)
        if result != mqtt.MQTT_ERR_SUCCESS:
            state["error"] = "Could not send the report subscription."

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            state["error"] = "Printer rejected the report subscription."
        else:
            print("Subscribed. Waiting up to 60 seconds for a nozzle temperature...")

    def on_message(client, userdata, message):
        if message.topic != topic:
            return
        state["messages"] += 1
        try:
            payload = json.loads(message.payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            print("Skipped an invalid report; its contents are not logged.")
            return
        report = payload.get("print") if isinstance(payload, dict) else None
        value = report.get("nozzle_temper") if isinstance(report, dict) else None
        if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 350:
            state["temperature"] = value

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    print("Connecting to the printer with certificate verification...")
    try:
        client.connect(host, port=8883, keepalive=30)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and state["temperature"] is None and not state["error"]:
            result = client.loop(timeout=1)
            if result != mqtt.MQTT_ERR_SUCCESS:
                state["error"] = "MQTT connection ended before a temperature was received."
        if state["error"]:
            print(state["error"])
            return 1
        if state["temperature"] is None:
            print(f"No nozzle temperature received. Report messages: {state['messages']}.")
            print("No value is assumed. P1 reports may contain only changed fields.")
            return 2
        print(f"Nozzle temperature: {state['temperature']:.2f} C")
        return 0
    finally:
        client.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ssl.SSLCertVerificationError as error:
        print("TLS certificate verification failed. Check the serial, certificates, and PC clock.")
        print("Verification reason:", error.verify_message)
        raise SystemExit(1)
    except (OSError, ValueError):
        print("Setup or connection failed. Check the IP, required settings, and HTTPS access to the public CA file.")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Stopped.")
        raise SystemExit(130)
